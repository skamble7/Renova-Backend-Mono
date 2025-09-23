from __future__ import annotations

import os
from typing import Any, Dict, Optional, List

import httpx
from pydantic import BaseModel


DEFAULT_TIMEOUT = float(os.getenv("HTTP_CLIENT_TIMEOUT_SECONDS", "30"))


class ServiceClientError(RuntimeError):
    def __init__(self, *, service: str, status: int, url: str, body: str):
        super().__init__(f"{service} HTTP {status}: {url} :: {body[:500]}")
        self.service = service
        self.status = status
        self.url = url
        self.body = body


class CapabilityServiceClient:
    """
    Thin async client for capability-service.

    Endpoints used:
      - GET /capability/packs/{pack_id}/resolved
      - GET /capability/packs/{pack_id}
      - GET /capability/{capability_id}
      - GET /integration/{integration_id}        <-- added
      - GET /integration                          <-- optional helper
      - GET /health
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        service_name_header: str = "learning-service",
    ):
        self.base_url = (base_url or os.getenv("CAPABILITY_SERVICE_BASE_URL", "")).rstrip("/")
        if not self.base_url:
            raise ValueError("CAPABILITY_SERVICE_BASE_URL is not set")
        self.timeout = timeout
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        self._service_name_header = service_name_header

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "CapabilityServiceClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    # ─────────────────────────────────────────────────────────────
    # Low-level request helper
    # ─────────────────────────────────────────────────────────────
    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        correlation_id: Optional[str] = None,
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Service-Name": self._service_name_header,
        }
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id

        url = f"{self.base_url}{path}"
        resp = await self._client.request(method, url, params=params, json=json, headers=headers)
        if resp.status_code >= 400:
            raise ServiceClientError(service="capability-service", status=resp.status_code, url=url, body=resp.text)
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    # ─────────────────────────────────────────────────────────────
    # Public methods
    # ─────────────────────────────────────────────────────────────
    async def health(self, *, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        return await self._request("GET", "/health", correlation_id=correlation_id)

    async def get_resolved_pack(self, pack_id: str, *, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch the ResolvedPackView for a published pack (server-flattened steps, may omit capabilities[]).
        GET /capability/packs/{pack_id}/resolved
        """
        return await self._request("GET", f"/capability/packs/{pack_id}/resolved", correlation_id=correlation_id)

    async def get_pack(self, pack_id: str, *, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch raw pack (not the resolved view).
        GET /capability/packs/{pack_id}
        """
        return await self._request("GET", f"/capability/packs/{pack_id}", correlation_id=correlation_id)

    async def get_capability(self, capability_id: str, *, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch a single capability (global definition).
        GET /capability/{capability_id}
        """
        return await self._request("GET", f"/capability/{capability_id}", correlation_id=correlation_id)

    async def get_integration(self, integration_id: str, *, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch a single MCP integration by ID.
        GET /integration/{integration_id}
        """
        return await self._request("GET", f"/integration/{integration_id}", correlation_id=correlation_id)

    async def list_integrations(
        self,
        *,
        q: Optional[str] = None,
        tag: Optional[str] = None,
        kind: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        correlation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List/search integrations.
        GET /integration?q=&tag=&kind=&limit=&offset=
        """
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if q is not None:
            params["q"] = q
        if tag is not None:
            params["tag"] = tag
        if kind is not None:
            params["kind"] = kind
        return await self._request("GET", "/integration", params=params, correlation_id=correlation_id)
