# services/learning-service/app/clients/artifact_service.py
from __future__ import annotations

import os
import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx

log = logging.getLogger("app.clients.artifact_service")

ARTIFACT_SVC_URL = os.getenv("ARTIFACT_SERVICE_URL", "http://renova-artifact-service:9011")
DEFAULT_HEADERS = {"Content-Type": "application/json"}

# Tunables
CONNECT_TIMEOUT = float(os.getenv("ARTIFACT_SVC_CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.getenv("ARTIFACT_SVC_READ_TIMEOUT", "40"))
WRITE_TIMEOUT = float(os.getenv("ARTIFACT_SVC_WRITE_TIMEOUT", "40"))
POOL_TIMEOUT = float(os.getenv("ARTIFACT_SVC_POOL_TIMEOUT", "40"))
MAX_RETRIES = int(os.getenv("ARTIFACT_SVC_MAX_RETRIES", "3"))
BASE_DELAY = float(os.getenv("ARTIFACT_SVC_RETRY_BASE_DELAY", "0.5"))
MAX_CONNECTIONS = int(os.getenv("HTTPX_MAX_CONNECTIONS", "50"))
MAX_KEEPALIVE = int(os.getenv("HTTPX_MAX_KEEPALIVE", "20"))

_timeout = httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=WRITE_TIMEOUT, pool=POOL_TIMEOUT)
_limits = httpx.Limits(max_connections=MAX_CONNECTIONS, max_keepalive_connections=MAX_KEEPALIVE)

# Single shared async client
_client: Optional[httpx.AsyncClient] = None

def _client_instance() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=_timeout, limits=_limits)
    return _client

async def _apost(path: str, json_body: Dict[str, Any], headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{ARTIFACT_SVC_URL}{path}"
    hdrs = {**DEFAULT_HEADERS, **(headers or {})}
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = _client_instance()
            r = await client.post(url, json=json_body, headers=hdrs, params=params)
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as e:
            last_err = e
            delay = BASE_DELAY * (2 ** (attempt - 1))
            log.warning("artifact_service.post.retry", extra={"path": path, "attempt": attempt, "max": MAX_RETRIES, "error": str(e), "sleep": delay})
            if attempt < MAX_RETRIES:
                await asyncio.sleep(delay)
    if last_err:
        log.error("artifact_service.post.failed", extra={"path": path, "error": str(last_err)})
        raise last_err
    return {}

async def _agetc(path: str, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{ARTIFACT_SVC_URL}{path}"
    hdrs = {**DEFAULT_HEADERS, **(headers or {})}
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = _client_instance()
            r = await client.get(url, headers=hdrs, params=params)
            r.raise_for_status()
            return r.json()
        except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as e:
            last_err = e
            delay = BASE_DELAY * (2 ** (attempt - 1))
            log.warning("artifact_service.get.retry", extra={"path": path, "attempt": attempt, "max": MAX_RETRIES, "error": str(e), "sleep": delay})
            if attempt < MAX_RETRIES:
                await asyncio.sleep(delay)
    if last_err:
        log.error("artifact_service.get.failed", extra={"path": path, "error": str(last_err)})
        raise last_err
    return {}

# --- API used by the learning service ---

async def upsert_batch(workspace_id: str, items: List[Dict[str, Any]], *, run_id: str = "") -> Dict[str, Any]:
    headers = {"X-Run-Id": run_id} if run_id else {}
    return await _apost(f"/artifact/{workspace_id}/upsert-batch", {"items": items}, headers=headers)

async def get_kinds_by_keys(keys: List[str]) -> Dict[str, Any]:
    """
    Artifact-service does NOT expose /registry/kinds/by-keys.
    Fetch each kind via GET /registry/kinds/{key} in parallel.
    Return shape: {"items":[...]} (skips missing/404 kinds).
    """
    cleaned = [k for k in (keys or []) if isinstance(k, str) and k.strip()]
    if not cleaned:
        return {"items": []}

    async def _one(k: str):
        path = f"/registry/kinds/{k}"
        try:
            return await _agetc(path)
        except Exception as e:
            # Swallow per-key failures so callers can still proceed with what we got.
            log.info("artifact_service.kind.fetch_failed", extra={"key": k, "error": str(e)})
            return None

    results = await asyncio.gather(*(_one(k) for k in cleaned))
    return {"items": [d for d in results if isinstance(d, dict)]}

async def get_workspace_with_artifacts(workspace_id: str, *, include_deleted: bool = False) -> Dict[str, Any]:
    return await _agetc(f"/workspace/{workspace_id}/with-artifacts", params={"include_deleted": str(include_deleted).lower()})

async def get_artifacts_by_ids(workspace_id: str, ids: List[str]) -> List[Dict[str, Any]]:
    resp = await _agetc(f"/artifact/{workspace_id}/by-ids", params={"ids": ",".join(ids)})
    return list(resp.get("items") or []) if isinstance(resp, dict) else []

async def get_workspace_parent(workspace_id: str) -> Dict[str, Any]:
    return await _agetc(f"/workspace/{workspace_id}/parent")

async def get_run_doc(run_id) -> Dict[str, Any]:
    return await _agetc(f"/run/{run_id}")
