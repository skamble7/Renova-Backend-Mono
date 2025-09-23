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
    Persistent STDIO transport using a simple JSON-RPC 2.0 over newline-delimited frames.
    """

    def __init__(self, integration_snapshot: Dict[str, Any], *, secret_resolver=None, runtime_vars: Optional[Dict[str, Any]] = None) -> None:
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
        self.startup_timeout_sec = int(os.getenv("MCP_STDIO_STARTUP_TIMEOUT", "20"))

        self._proc: Optional[Process] = None
        self._stdout_reader_task: Optional[asyncio.Task] = None
        self._stderr_reader_task: Optional[asyncio.Task] = None

        self._resp_q: asyncio.Queue[str] = asyncio.Queue()
        self._ready_q: asyncio.Queue[str] = asyncio.Queue()

        self._lock = asyncio.Lock()
        self._secret_resolver = secret_resolver

    async def connect(self) -> None:
        if self._proc and self._proc.returncode is None:
            return

        env = os.environ.copy()
        env.update(self.static_env)

        # Resolve env aliases
        for key, alias in self.env_aliases.items():
            val = None
            if self._secret_resolver:
                val = self._secret_resolver(alias)
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

        if self.readiness_regex:
            pattern = re.compile(self.readiness_regex)
            try:
                await asyncio.wait_for(self._wait_for_ready(pattern), timeout=self.startup_timeout_sec)
                logger.info("STDIO: readiness matched pattern=%s", self.readiness_regex)
            except asyncio.TimeoutError:
                await self.aclose()
                raise RuntimeError("STDIO transport readiness timed out")

    async def _reader_stdout(self, stream: asyncio.StreamReader) -> None:
        try:
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
                try:
                    self._ready_q.put_nowait(line)
                except Exception:
                    pass
                try:
                    self._resp_q.put_nowait(line)
                except Exception:
                    pass
        except Exception:
            pass

    async def _reader_stderr(self, stream: asyncio.StreamReader) -> None:
        try:
            while True:
                line_bytes = await stream.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\r\n")
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

    async def aclose(self) -> None:
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

    async def _ensure_connected(self) -> None:
        if not self._proc or self._proc.returncode is not None:
            if not self.restart_on_exit and self._proc is not None:
                raise RuntimeError("STDIO process exited and restart_on_exit is False")
            await self.connect()

    async def call_tool(
        self,
        tool: str,
        args: Dict[str, Any],
        *,
        timeout_sec: Optional[float] = None,
        correlation_id: Optional[str] = None,
    ) -> Any:
        await self._ensure_connected()
        assert self._proc is not None and self._proc.stdin is not None

        req_id = uuid.uuid4().hex
        frame = json.dumps(
            {"jsonrpc": "2.0", "id": req_id, "method": tool, "params": args},
            separators=(",", ":"),
            ensure_ascii=False,
        ) + "\n"

        logger.info("STDIO: send tool=%s timeout=%s args.keys=%s", tool, timeout_sec, list(args.keys())[:8])

        async with self._lock:
            self._proc.stdin.write(frame.encode("utf-8"))
            await self._proc.stdin.drain()

            deadline = asyncio.get_event_loop().time() + (timeout_sec or 60.0)
            while True:
                timeout = deadline - asyncio.get_event_loop().time()
                if timeout <= 0:
                    raise TimeoutError(f"STDIO tool call timed out: {tool}")

                try:
                    line = await asyncio.wait_for(self._resp_q.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    raise TimeoutError(f"STDIO tool call timed out: {tool}")

                try:
                    obj = json.loads(line)
                except Exception:
                    continue

                if obj.get("id") != req_id:
                    continue

                if "error" in obj:
                    raise RuntimeError(f"STDIO tool error: {obj['error']}")
                return obj.get("result")
