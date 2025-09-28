# services/learning-service/app/integrations/transport_stdio.py
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
import logging
from asyncio.subprocess import Process
from typing import Any, Dict, Optional

logger = logging.getLogger("app.transport.stdio")


class StdioTransport:
    """
    Persistent STDIO transport using JSON-RPC 2.0.

    Protocol implemented:
      - initialize  -> result with serverInfo/capabilities
      - notifications/initialized (fire-and-forget)
      - tools/call  -> invoke a named tool with arguments

    Framing support:
      - MCP framed mode:   `Content-Length: N\\r\\n\\r\\n<JSON bytes>`
      - Line-delimited:    one compact JSON object per line

    Behavior:
      - If timeout_sec=None is passed to call_tool(), we will wait indefinitely
        for the server's response UNLESS the underlying process exits; in that case
        we raise RuntimeError("STDIO process closed before response").
      - We do not inspect or mutate tool arguments here; higher layers remain
        responsible for interpolation/validation.
    """

    def __init__(
        self,
        integration_snapshot: Dict[str, Any],
        *,
        secret_resolver=None,
        runtime_vars: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.snapshot = integration_snapshot or {}
        t = self.snapshot.get("transport") or {}
        self._runtime_vars = runtime_vars or {}

        def subst(val):
            if not isinstance(val, str):
                return val
            out = val
            for k, v in self._runtime_vars.items():
                out = out.replace(f"${{{k}}}", str(v))
            return out

        # Transport config
        self.command: str = subst(t.get("command") or "")
        if not self.command:
            raise ValueError("StdioTransport requires transport.command")
        self.args = [subst(a) for a in (t.get("args") or [])]
        self.cwd = subst(t.get("cwd") or None)
        self.static_env = {k: subst(v) for k, v in (t.get("env") or {}).items()}
        self.env_aliases = dict(t.get("env_aliases") or {})
        self.restart_on_exit = bool(t.get("restart_on_exit", True))
        self.readiness_regex = subst(t.get("readiness_regex") or None)
        self.kill_timeout_sec = int(t.get("kill_timeout_sec") or os.getenv("MCP_STDIO_KILL_TIMEOUT", "10"))
        self.startup_timeout_sec = int(os.getenv("MCP_STDIO_STARTUP_TIMEOUT", "60"))

        # Process & IO
        self._proc: Optional[Process] = None
        self._stdout_reader_task: Optional[asyncio.Task] = None
        self._stderr_reader_task: Optional[asyncio.Task] = None

        # Queues
        # Parsed JSON objects (dict) are pushed here by the reader.
        self._resp_q: asyncio.Queue[Any] = asyncio.Queue()
        self._ready_q: asyncio.Queue[str] = asyncio.Queue()

        # State
        self._lock = asyncio.Lock()
        self._secret_resolver = secret_resolver
        self._initialized: bool = False  # JSON-RPC handshake done

    # ---------- lifecycle ----------

    async def connect(self) -> None:
        """Launch the stdio subprocess, wait for readiness banner (if configured), then JSON-RPC initialize."""
        if self._proc and self._proc.returncode is None:
            return

        env = os.environ.copy()
        env.update(self.static_env)

        # Resolve env aliases from secret store or process env
        for key, alias in self.env_aliases.items():
            val = None
            if self._secret_resolver:
                try:
                    val = self._secret_resolver(alias)
                except Exception:
                    val = None
            if val is None:
                val = os.getenv(alias)
            if val is not None:
                env[key] = val

        logger.info("STDIO: launching command=%s args=%s cwd=%s", self.command, self.args, self.cwd)

        self._proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            cwd=self.cwd or None,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        assert self._proc.stdout is not None and self._proc.stderr is not None
        self._stdout_reader_task = asyncio.create_task(self._reader_stdout(self._proc.stdout))
        self._stderr_reader_task = asyncio.create_task(self._reader_stderr(self._proc.stderr))

        # Wait for readiness banner if provided (server prints "mcp server ready")
        if self.readiness_regex:
            pattern = re.compile(self.readiness_regex)
            try:
                await asyncio.wait_for(self._wait_for_ready(pattern), timeout=self.startup_timeout_sec)
                logger.info("STDIO: readiness matched pattern=%s", self.readiness_regex)
            except asyncio.TimeoutError:
                await self.aclose()
                raise RuntimeError("STDIO transport readiness timed out")

        # JSON-RPC handshake (initialize + notifications/initialized)
        try:
            await asyncio.wait_for(self._handshake(), timeout=self.startup_timeout_sec)
            self._initialized = True
        except asyncio.TimeoutError:
            await self.aclose()
            raise RuntimeError("STDIO transport initialize timed out")

    async def aclose(self) -> None:
        """Tear down IO tasks and process."""
        for task in (self._stdout_reader_task, self._stderr_reader_task):
            if task:
                task.cancel()
        self._stdout_reader_task = None
        self._stderr_reader_task = None

        if self._proc:
            try:
                if self._proc.stdin:
                    self._proc.stdin.close()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=self.kill_timeout_sec)
                except asyncio.TimeoutError:
                    self._proc.kill()
            finally:
                self._proc = None
                self._initialized = False

    async def _ensure_connected(self) -> None:
        """Ensure process is alive and handshake completed."""
        if not self._proc or self._proc.returncode is not None:
            if not self.restart_on_exit and self._proc is not None:
                raise RuntimeError("STDIO process exited and restart_on_exit is False")
            await self.connect()
        elif not self._initialized:
            await self._handshake()

    # ---------- IO readers ----------

    async def _reader_stdout(self, stream: asyncio.StreamReader) -> None:
        """
        Supports BOTH:
          1) MCP framing:   Content-Length: N\\r\\n\\r\\n<JSON bytes...>
          2) Line-delimited: one compact JSON object per line

        Every parsed JSON object (dict) is put onto _resp_q.
        """
        try:
            while True:
                # Try to read the first header/line
                header_line = await stream.readline()
                if not header_line:
                    break
                header_text = header_line.decode("utf-8", errors="replace").rstrip("\r\n")

                # Some servers print readiness banners on stdout as well
                try:
                    self._ready_q.put_nowait(header_text)
                except Exception:
                    pass

                if header_text.lower().startswith("content-length:"):
                    # -------- Framed mode (MCP) --------
                    try:
                        _, n_str = header_text.split(":", 1)
                        length = int(n_str.strip())
                    except Exception:
                        # Malformed header; skip to next line
                        continue
                    # Expect the blank line separator
                    sep = await stream.readline()  # should be b"\r\n" or b"\n"
                    if not sep:
                        break
                    # Read exactly N bytes for the JSON body
                    try:
                        body = await stream.readexactly(length)
                    except asyncio.IncompleteReadError as e:
                        # Process likely exited; stop reader
                        break
                    try:
                        obj = json.loads(body.decode("utf-8", errors="replace"))
                        self._resp_q.put_nowait(obj)
                    except Exception:
                        # If body isn't JSON, ignore and continue
                        continue
                else:
                    # -------- Fallback line-delimited mode --------
                    line = header_text
                    # Only attempt to parse if it looks like a JSON object/array
                    if not line or not (line.lstrip().startswith("{") or line.lstrip().startswith("[")):
                        continue
                    try:
                        obj = json.loads(line)
                        self._resp_q.put_nowait(obj)
                    except Exception:
                        # If pretty-printed JSON arrives without framing, we don't accumulate here
                        # to avoid blocking; servers should emit compact JSON for this mode.
                        continue
        except Exception:
            # Never crash the process because of reader issues; let caller handle timeouts.
            pass

    async def _reader_stderr(self, stream: asyncio.StreamReader) -> None:
        try:
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
                # many servers print "mcp server ready" on stderr
                try:
                    self._ready_q.put_nowait(line)
                except Exception:
                    pass
                logger.debug("STDIO[stderr]: %s", line)
        except Exception:
            pass

    async def _wait_for_ready(self, pattern: re.Pattern[str]) -> None:
        while True:
            line = await self._ready_q.get()
            if pattern.search(line):
                return

    # ---------- JSON-RPC helpers ----------

    async def _send_json(self, obj: Dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        frame = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
        self._proc.stdin.write(frame.encode("utf-8"))
        await self._proc.stdin.drain()

    async def _wait_for_response(self, req_id: str, timeout: Optional[float]) -> Dict[str, Any]:
        """
        Drain _resp_q until a JSON object with matching id arrives.

        If timeout is None, wait indefinitely (until a matching response arrives) unless
        the subprocess exits and the response queue is empty, in which case raise RuntimeError.
        """
        loop = asyncio.get_event_loop()

        if timeout is None:
            while True:
                # If the process died and there's nothing left to read, abort.
                if self._proc and self._proc.returncode is not None and self._resp_q.empty():
                    raise RuntimeError("STDIO process closed before response")
                item = await self._resp_q.get()
                obj = item if isinstance(item, dict) else None
                if isinstance(item, str):
                    try:
                        obj = json.loads(item)
                    except Exception:
                        obj = None
                if isinstance(obj, dict) and obj.get("id") == req_id:
                    return obj
        else:
            deadline = loop.time() + float(timeout)
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                item = await asyncio.wait_for(self._resp_q.get(), timeout=remaining)
                obj = item if isinstance(item, dict) else None
                if isinstance(item, str):
                    try:
                        obj = json.loads(item)
                    except Exception:
                        obj = None
                if isinstance(obj, dict) and obj.get("id") == req_id:
                    return obj

    async def _handshake(self) -> None:
        """initialize -> result, then send notifications/initialized (no response)."""
        if self._initialized:
            return
        init_id = uuid.uuid4().hex
        await self._send_json({"jsonrpc": "2.0", "id": init_id, "method": "initialize", "params": {}})
        resp = await self._wait_for_response(init_id, timeout=self.startup_timeout_sec)
        if "error" in resp:
            raise RuntimeError(f"STDIO initialize failed: {resp['error']}")
        await self._send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True
        logger.info("STDIO: JSON-RPC handshake completed")

    # ---------- public API ----------

    async def call_tool(
        self,
        tool: str,
        args: Dict[str, Any],
        *,
        timeout_sec: Optional[float] = None,
        correlation_id: Optional[str] = None,  # kept for symmetry; unused here
    ) -> Any:
        """
        Invoke a tool via JSON-RPC:
          method: "tools/call"
          params: { "name": <tool>, "arguments": { ... } }

        Behavior:
          - If timeout_sec is None, wait indefinitely for the response (unless the process exits).
          - If timeout_sec is a number, enforce it and raise TimeoutError on expiry.
        """
        await self._ensure_connected()
        assert self._proc is not None

        req_id = uuid.uuid4().hex
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        }

        logger.info(
            "STDIO: send tool=%s timeout=%s args.keys=%s",
            tool,
            timeout_sec,
            list(args.keys())[:8],
        )

        async with self._lock:
            await self._send_json(payload)

            try:
                resp = await self._wait_for_response(req_id, timeout=timeout_sec)
            except asyncio.TimeoutError:
                raise TimeoutError(f"STDIO tool call timed out: {tool}")

            if "error" in resp:
                raise RuntimeError(f"STDIO tool error: {resp['error']}")

            return resp.get("result")
