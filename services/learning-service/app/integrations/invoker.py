from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional

from app.integrations.transport_http import HTTPTransport
from app.integrations.transport_stdio import StdioTransport


SecretResolver = Callable[[str], Optional[str]]
"""
A simple resolver signature for secret aliases:
Given an alias (e.g., 'alias.cobol.token'), return the resolved secret string.
This service does not implement secret storage; you can wire a resolver later.
"""


class IntegrationInvoker:
    """
    Facade for invoking a single tool on a given integration snapshot.

    Usage:
        invoker = IntegrationInvoker(integration_snapshot, secret_resolver=my_resolver)
        result = await invoker.call_tool("parse_copybooks", {"path": "/code"}, timeout_sec=60, retries=1)
    """

    def __init__(
        self,
        integration_snapshot: Dict[str, Any],
        *,
        secret_resolver: Optional[SecretResolver] = None,
    ) -> None:
        self.snapshot = integration_snapshot or {}
        self.transport_kind: str = (self.snapshot.get("transport") or {}).get("kind", "").lower()
        self.secret_resolver = secret_resolver
        self._transport = None

        if self.transport_kind == "http":
            self._transport = HTTPTransport(self.snapshot, secret_resolver=secret_resolver)
        elif self.transport_kind == "stdio":
            self._transport = StdioTransport(self.snapshot, secret_resolver=secret_resolver)
        else:
            raise ValueError(f"Unsupported transport kind: {self.transport_kind!r}")

    async def aclose(self) -> None:
        if self._transport and hasattr(self._transport, "aclose"):
            await self._transport.aclose()  # type: ignore[attr-defined]

    async def __aenter__(self) -> "IntegrationInvoker":
        # Ensure connect if transport requires it (stdio)
        if hasattr(self._transport, "connect"):
            await self._transport.connect()  # type: ignore[attr-defined]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

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
        Invoke a tool with optional retries. Retries are basic linear retries here;
        the agent layer may add richer policies later.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(max(1, retries + 1)):
            try:
                return await self._transport.call_tool(  # type: ignore[attr-defined]
                    tool,
                    args,
                    timeout_sec=timeout_sec,
                    correlation_id=correlation_id,
                )
            except Exception as e:  # pragma: no cover
                last_exc = e
                if attempt < retries:
                    await asyncio.sleep(0.25 * (attempt + 1))
                else:
                    raise
        if last_exc:
            raise last_exc
