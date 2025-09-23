from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Dict, Optional, Set

from app.integrations.transport_http import HTTPTransport
from app.integrations.transport_stdio import StdioTransport

SecretResolver = Callable[[str], Optional[str]]

log = logging.getLogger("app.integrations.invoker")


class IntegrationInvoker:
    """
    Facade for invoking tools on a given integration snapshot.
    Supports stdio/http transports and passes runtime_vars for ${...} interpolation.

    Also sanitizes tool arguments to avoid sending framework metadata
    (e.g., `inputs`, `context`) that violates strict JSON Schemas on MCP tools.
    """

    def __init__(
        self,
        integration_snapshot: Dict[str, Any],
        *,
        secret_resolver: Optional[SecretResolver] = None,
        runtime_vars: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.snapshot = integration_snapshot or {}
        self.transport_kind: str = (self.snapshot.get("transport") or {}).get("kind", "").lower()
        self.secret_resolver = secret_resolver
        self.runtime_vars = runtime_vars or {}
        self._transport = None

        # Known meta keys added by our graph/runtime that must never be sent to tools.
        self._meta_arg_names: Set[str] = {
            "inputs",
            "context",
            "correlation_id",
            "correlationId",
            "__metadata__",
        }

        # Optional: build a map of allowed input keys per tool from the snapshot,
        # if the snapshot already contains tool metadata (schema properties).
        self._tool_allowed_keys: Dict[str, Set[str]] = {}
        try:
            tools = self.snapshot.get("tools") or []
            for t in tools:
                name = t.get("name") or t.get("tool", {}).get("name")
                schema = t.get("input_schema") or t.get("inputSchema") or {}
                props = (schema.get("properties") or {})
                if name and isinstance(props, dict):
                    self._tool_allowed_keys[name] = set(props.keys())
        except Exception:  # snapshot shape is flexible; best-effort only
            pass

        if self.transport_kind == "http":
            self._transport = HTTPTransport(
                self.snapshot,
                secret_resolver=secret_resolver,
                runtime_vars=self.runtime_vars,
            )
        elif self.transport_kind == "stdio":
            self._transport = StdioTransport(
                self.snapshot,
                secret_resolver=secret_resolver,
                runtime_vars=self.runtime_vars,
            )
        else:
            raise ValueError(f"Unsupported transport kind: {self.transport_kind!r}")

    async def aclose(self) -> None:
        if self._transport and hasattr(self._transport, "aclose"):
            await self._transport.aclose()  # type: ignore[attr-defined]

    async def __aenter__(self) -> "IntegrationInvoker":
        if hasattr(self._transport, "connect"):
            await self._transport.connect()  # type: ignore[attr-defined]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    # -----------------------
    # Internal helpers
    # -----------------------
    def _sanitize_args(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove framework metadata and, if we know the tool's schema,
        drop any keys not declared in the schema properties.
        """
        if not isinstance(args, dict):
            return {}

        # 1) Drop known framework metadata keys
        clean = {k: v for k, v in args.items() if k not in self._meta_arg_names}

        # 2) If we have an allow-list for this tool, filter to those keys only
        allowed = self._tool_allowed_keys.get(tool_name)
        if allowed:
            clean = {k: v for k, v in clean.items() if k in allowed}

        return clean

    # -----------------------
    # Public API
    # -----------------------
    async def call_tool(
        self,
        tool: str,
        args: Dict[str, Any],
        *,
        timeout_sec: Optional[float] = None,
        retries: int = 0,
        correlation_id: Optional[str] = None,
    ) -> Any:
        """
        Invoke a tool with optional retries. Arguments are sanitized to satisfy
        strict MCP tool schemas (no extraneous properties).
        """
        # Backoff configuration (milliseconds) for retries; defaults align with compose env.
        backoff_ms = int(os.getenv("MCP_RETRY_BACKOFF_MS", "250"))

        last_exc: Optional[Exception] = None
        for attempt in range(max(1, retries + 1)):
            try:
                safe_args = self._sanitize_args(tool, args or {})
                return await self._transport.call_tool(  # type: ignore[attr-defined]
                    tool,
                    safe_args,
                    timeout_sec=timeout_sec,
                    correlation_id=correlation_id,
                )
            except Exception as e:  # pragma: no cover
                last_exc = e
                if attempt < retries:
                    sleep_s = (backoff_ms / 1000.0) * (attempt + 1)
                    try:
                        await asyncio.sleep(sleep_s)
                    except asyncio.CancelledError:
                        raise
                else:
                    raise
        if last_exc:
            raise last_exc
