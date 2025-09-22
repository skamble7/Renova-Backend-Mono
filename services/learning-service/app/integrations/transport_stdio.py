from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from asyncio.subprocess import Process
from typing import Any, Dict, Optional


class StdioTransport:
    """
    Persistent STDIO transport using a simple JSON-RPC 2.0 over newline-delimited frames.

    Contract expectations (from integration snapshot):
      transport.kind = "stdio"
      transport.command : str
      transport.args? : list[str]
      transport.cwd? : str
      transport.env? : dict[str,str] (static, non-secret)
      transport.env_aliases? : dict[str,str] (key -> alias name; resolved via secret_resolver or env var)
      transport.restart_on_exit? : bool
      transport.readiness_regex? : str (waits for a matching line on stdout)
      transport.kill_timeout_sec? : int

    Invocation protocol (assumed default):
      Send:   {"jsonrpc":"2.0","id":"<uuid>","method":"<tool>","params":{...}}\n
      Expect: {"jsonrpc":"2.0","id":"<uuid>","result": ... }   OR   {"error": {...}}

    If your server uses a different framing, adapt `_send_and_recv`.
    """

    def __init__(self, integration_snapshot: Dict[str, Any], *, secret_resolver=None) -> None:
        self.snapshot = integration_snapshot or {}
        t = self.snapshot.get("transport") or {}
        self.command: str = t.get("command") or ""
        if not self.command:
            raise ValueError("StdioTransport requires transport.command")
        self.args = list(t.get("args") or [])
        self.cwd = t.get("cwd") or None
        self.static_env = dict(t.get("env") or {})
        self.env_aliases = dict(t.get("env_aliases") or {})
        self.restart_on_exit = bool(t.get("restart_on_exit", True))
        self.readiness_regex = t.get("readiness_regex") or None
        self.kill_timeout_sec = int(t.get("kill_timeout_sec") or os.getenv("MCP_STDIO_KILL_TIMEOUT", "10"))
        self.startup_timeout_sec = int(os.getenv("MCP_STDIO_STARTUP_TIMEOUT", "20"))

        self._proc: Optional[Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._buffer = asyncio.Queue()  # lines from stdout
        self._lock = asyncio.Lock()
        self._secret_resolver = secret_resolver

    async def connect(self) -> None:
        if self._proc and self._proc.returncode is None:
            return

        env = os.environ.copy()
        env.update(self.static_env)

        # Resolve aliases: values are alias names that map to secret strings via resolver or env
        for key, alias in self.env_aliases.items():
            val = None
            if self._secret_resolver:
                val = self._secret_resolver(alias)
            if val is None:
                val = os.getenv(alias)
            if val is not None:
                env[key] = val

        self._proc = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            cwd=self.cwd or None,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Start reader task to continuously read stdout lines
        assert self._proc.stdout is not None
        self._reader_task = asyncio.create_task(self._reader(self._proc.stdout))

        # Optionally wait for readiness
        if self.readiness_regex:
            pattern = re.compile(self.readiness_regex)
            try:
                await asyncio.wait_for(self._wait_for_output(pattern), timeout=self.startup_timeout_sec)
            except asyncio.TimeoutError:
                await self.aclose()
                raise RuntimeError("STDIO transport readiness timed out")

    async def _reader(self, stream: asyncio.StreamReader) -> None:
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                try:
                    self._buffer.put_nowait(line.decode("utf-8", errors="replace").rstrip("\r\n"))
                except Exception:
                    # If buffer is full or closed, drop line silently
                    pass
        except Exception:
            pass

    async def _wait_for_output(self, pattern: re.Pattern[str]) -> None:
        while True:
            line = await self._buffer.get()
            if pattern.search(line):
                return

    async def aclose(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
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
        correlation_id: Optional[str] = None,  # not used in stdio, but kept for symmetry
    ) -> Any:
        await self._ensure_connected()
        assert self._proc is not None and self._proc.stdin is not None

        req_id = uuid.uuid4().hex
        frame = json.dumps(
            {"jsonrpc": "2.0", "id": req_id, "method": tool, "params": args},
            separators=(",", ":"),
            ensure_ascii=False,
        ) + "\n"

        async with self._lock:
            self._proc.stdin.write(frame.encode("utf-8"))
            await self._proc.stdin.drain()
            # Wait for a matching response line
            deadline = asyncio.get_event_loop().time() + (timeout_sec or 60.0)
            while True:
                timeout = deadline - asyncio.get_event_loop().time()
                if timeout <= 0:
                    raise TimeoutError(f"STDIO tool call timed out: {tool}")

                try:
                    line = await asyncio.wait_for(self._buffer.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    raise TimeoutError(f"STDIO tool call timed out: {tool}")

                try:
                    obj = json.loads(line)
                except Exception:
                    # Not a JSON line; ignore
                    continue

                if obj.get("id") != req_id:
                    # Not our response; re-queue or drop
                    # (Dropping to keep it simple; servers should reply in order)
                    continue

                if "error" in obj:
                    raise RuntimeError(f"STDIO tool error: {obj['error']}")
                return obj.get("result")
