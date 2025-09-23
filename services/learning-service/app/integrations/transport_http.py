from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx


class HTTPTransport:
    """
    Generic HTTP transport for MCP-like integrations.
    """

    def __init__(self, integration_snapshot: Dict[str, Any], *, secret_resolver=None, runtime_vars: Optional[Dict[str, Any]] = None) -> None:
        self.snapshot = integration_snapshot or {}
        t = self.snapshot.get("transport") or {}
        self._runtime_vars = runtime_vars or {}

        def subst(s: Optional[str]) -> Optional[str]:
            if not isinstance(s, str):
                return s
            out = s
            for k, v in self._runtime_vars.items():
                out = out.replace(f"${{{k}}}", str(v))
            return out

        self.base_url: str = (subst(t.get("base_url")) or "").rstrip("/")
        if not self.base_url:
            raise ValueError("HTTPTransport requires transport.base_url")
        self.static_headers: Dict[str, str] = {k: subst(v) or "" for k, v in (t.get("headers") or {}).items()}
        self.auth: Dict[str, Any] = dict(t.get("auth") or {})
        self.invoke_path: str = subst(t.get("invoke_path")) or "/invoke"
        self.timeout = float(os.getenv("MCP_HTTP_TIMEOUT", "60"))
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        self._secret_resolver = secret_resolver

    async def aclose(self) -> None:
        await self._client.aclose()

    def _resolve_auth_headers(self) -> Dict[str, str]:
        method = (self.auth.get("method") or "none").lower()
        if method == "none":
            return {}
        # Helper to resolve an alias by name via resolver or env var
        def res(key: str) -> Optional[str]:
            if not key:
                return None
            if self._secret_resolver:
                v = self._secret_resolver(key)
                if v:
                    return v
            # fallback to env var by alias name
            return os.getenv(key)

        headers: Dict[str, str] = {}
        if method == "bearer":
            token_alias = self.auth.get("token_alias")
            token = res(token_alias)
            if token:
                headers["Authorization"] = f"Bearer {token}"
        elif method == "basic":
            user_alias = self.auth.get("username_alias")
            pass_alias = self.auth.get("password_alias")
            import base64
            user = res(user_alias) or ""
            pwd = res(pass_alias) or ""
            b64 = base64.b64encode(f"{user}:{pwd}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {b64}"
        elif method == "api_key":
            header = self.auth.get("header") or "X-API-Key"
            key_alias = self.auth.get("key_alias")
            key = res(key_alias)
            if key:
                headers[header] = key
        return headers

    async def call_tool(
        self,
        tool: str,
        args: Dict[str, Any],
        *,
        timeout_sec: Optional[float] = None,
        correlation_id: Optional[str] = None,
    ) -> Any:
        headers: Dict[str, str] = {"Accept": "application/json", "Content-Type": "application/json"}
        headers.update(self.static_headers)
        headers.update(self._resolve_auth_headers())
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id

        payload = {"tool": tool, "args": args}
        resp = await self._client.post(self.invoke_path, json=payload, headers=headers, timeout=timeout_sec or self.timeout)
        resp.raise_for_status()
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text
