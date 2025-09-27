# services/learning-service/app/clients/artifact_service.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx
from pydantic import UUID4


DEFAULT_TIMEOUT = float(os.getenv("HTTP_CLIENT_TIMEOUT_SECONDS", "30"))


class ServiceClientError(RuntimeError):
    def __init__(self, *, service: str, status: int, url: str, body: str):
        super().__init__(f"{service} HTTP {status}: {url} :: {body[:500]}")
        self.service = service
        self.status = status
        self.url = url
        self.body = body


class ArtifactServiceClient:
    """
    Thin async client for artifact-service.

    Endpoints used now:
      - GET  /registry/kinds/{kind_id}
      - GET  /registry/kinds/{kind_id}/prompt
      - POST /registry/validate
      - GET  /artifact/{workspace_id}/parent
      - POST /artifact/{workspace_id}/upsert-batch
      - GET  /artifact/{workspace_id} (optional helper)
      - GET  /artifact/{workspace_id}/deltas (optional helper)
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        service_name_header: str = "learning-service",
    ):
        self.base_url = (base_url or os.getenv("ARTIFACT_SERVICE_BASE_URL", "")).rstrip("/")
        if not self.base_url:
            raise ValueError("ARTIFACT_SERVICE_BASE_URL is not set")
        self.timeout = timeout
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        self._service_name_header = service_name_header

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ArtifactServiceClient":
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
        run_id: Optional[str] = None,
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Service-Name": self._service_name_header,
        }
        if correlation_id:
            headers["X-Correlation-ID"] = correlation_id
        if run_id:
            headers["X-Run-Id"] = str(run_id)

        url = f"{self.base_url}{path}"
        resp = await self._client.request(method, url, params=params, json=json, headers=headers)
        if resp.status_code >= 400:
            raise ServiceClientError(service="artifact-service", status=resp.status_code, url=url, body=resp.text)
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    # ─────────────────────────────────────────────────────────────
    # Registry (schema/prompt/validation)
    # ─────────────────────────────────────────────────────────────
    async def get_kind(self, kind_id: str, *, correlation_id: Optional[str] = None) -> Dict[str, Any]:
        """
        GET /registry/kinds/{kind_id}
        Returns the full Kind definition (includes schema versions, identity, depends_on, etc.)
        """
        return await self._request("GET", f"/registry/kinds/{kind_id}", correlation_id=correlation_id)

    async def get_prompt(
        self,
        kind_id: str,
        *,
        version: Optional[str] = None,
        paradigm: Optional[str] = None,
        style: Optional[str] = None,
        format: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        GET /registry/kinds/{kind_id}/prompt?version=&paradigm=&style=&format=
        Returns the canonical prompt contract for this kind/version.
        """
        params: Dict[str, Any] = {}
        if version:
            params["version"] = version
        if paradigm:
            params["paradigm"] = paradigm
        if style:
            params["style"] = style
        if format:
            params["format"] = format
        return await self._request("GET", f"/registry/kinds/{kind_id}/prompt", params=params, correlation_id=correlation_id)

    async def validate_kind_data(
        self,
        *,
        kind_id: str,
        data: Dict[str, Any],
        version: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /registry/validate
        Body: { kind, data, version? }
        Response: { ok: True, kind, version } or validation errors (HTTP 400/422).
        """
        body: Dict[str, Any] = {"kind": kind_id, "data": data}
        if version:
            body["version"] = version
        return await self._request("POST", "/registry/validate", json=body, correlation_id=correlation_id)

    # ─────────────────────────────────────────────────────────────
    # Workspace artifacts (baseline & listing)
    # ─────────────────────────────────────────────────────────────
    async def get_workspace_parent(
        self,
        workspace_id: UUID4,
        *,
        include_deleted: bool = False,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        GET /artifact/{workspace_id}/parent
        Returns the WorkspaceArtifactsDoc with embedded artifacts.
        """
        params = {"include_deleted": str(bool(include_deleted)).lower()}
        return await self._request("GET", f"/artifact/{workspace_id}/parent", params=params, correlation_id=correlation_id)

    async def list_workspace_artifacts(
        self,
        workspace_id: UUID4,
        *,
        kind: Optional[str] = None,
        name_prefix: Optional[str] = None,
        include_deleted: bool = False,
        limit: int = 200,
        offset: int = 0,
        correlation_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        GET /artifact/{workspace_id}
        Convenience helper to list artifacts by kind or name prefix.
        """
        params: Dict[str, Any] = {
            "include_deleted": str(bool(include_deleted)).lower(),
            "limit": max(1, min(500, int(limit))),
            "offset": max(0, int(offset)),
        }
        if kind:
            params["kind"] = kind
        if name_prefix:
            params["name_prefix"] = name_prefix

        return await self._request("GET", f"/artifact/{workspace_id}", params=params, correlation_id=correlation_id)

    async def upsert_batch(
        self,
        workspace_id: UUID4,
        items: List[Dict[str, Any]],
        *,
        correlation_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /artifact/{workspace_id}/upsert-batch
        Body: { items: List[ArtifactItemCreate] }
        Returns a summary dict (counts, results) per artifact-service contract.
        """
        body = {"items": items}
        return await self._request(
            "POST",
            f"/artifact/{workspace_id}/upsert-batch",
            json=body,
            correlation_id=correlation_id,
            run_id=run_id,
        )

    async def get_deltas(
        self,
        workspace_id: UUID4,
        *,
        run_id: Optional[str] = None,
        include_ids: bool = False,
        correlation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        GET /artifact/{workspace_id}/deltas?run_id=&include_ids=
        Useful if you want artifact-service to compute/verify deltas as well.
        """
        params: Dict[str, Any] = {"include_ids": str(bool(include_ids)).lower()}
        if run_id:
            params["run_id"] = run_id
        return await self._request("GET", f"/artifact/{workspace_id}/deltas", params=params, correlation_id=correlation_id)
