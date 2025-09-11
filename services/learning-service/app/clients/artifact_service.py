# services/learning-service/app/clients/artifact_service.py
from __future__ import annotations
import os
import asyncio
from typing import Any, Dict, List, Optional
import httpx
from app.config import settings

ARTIFACT_SVC_URL = settings.ARTIFACT_SERVICE_URL

async def _aget(url: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_S) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        return r

async def _apost(url: str, json_body: Any, headers: Optional[Dict[str, str]] = None, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_S) as client:
        r = await client.post(url, json=json_body, headers=headers or {}, params=params)
        r.raise_for_status()
        return r

async def get_workspace_with_artifacts(workspace_id: str, include_deleted: bool = False) -> Dict[str, Any]:
    url = f"{ARTIFACT_SVC_URL}/artifact/{workspace_id}/parent"
    params = {"include_deleted": "true"} if include_deleted else None
    resp = await _aget(url, params=params)
    return resp.json()

async def upsert_batch(workspace_id: str, items: List[Dict[str, Any]], run_id: Optional[str] = None) -> Dict[str, Any]:
    url = f"{ARTIFACT_SVC_URL}/artifact/{workspace_id}/upsert-batch"
    headers = {"X-Run-Id": run_id} if run_id else {}
    resp = await _apost(url, {"items": items}, headers=headers)
    return resp.json()

async def upsert_single(workspace_id: str, item: Dict[str, Any], run_id: Optional[str] = None) -> Dict[str, Any]:
    url = f"{ARTIFACT_SVC_URL}/artifact/{workspace_id}"
    headers = {"X-Run-Id": run_id} if run_id else {}
    resp = await _apost(url, item, headers=headers)
    return resp.json()

async def get_workspace_parent(workspace_id: str, include_deleted: bool = False) -> Dict[str, Any]:
    url = f"{ARTIFACT_SVC_URL}/artifact/{workspace_id}/parent"
    params = {"include_deleted": "true"} if include_deleted else None
    resp = await _aget(url, params=params)
    return resp.json()

async def get_artifacts_by_ids(workspace_id: str, artifact_ids: List[str]) -> List[Dict[str, Any]]:
    if not artifact_ids:
        return []
    async with httpx.AsyncClient(timeout=30.0) as client:
        async def _fetch(aid: str):
            try:
                r = await client.get(f"{ARTIFACT_SVC_URL}/artifact/{workspace_id}/{aid}")
                r.raise_for_status()
                return r.json()
            except httpx.HTTPStatusError:
                return None
        results = await asyncio.gather(*(_fetch(a) for a in artifact_ids))
        return [r for r in results if isinstance(r, dict)]

async def get_run_doc(run_id):
    # convenience if artifact-service exposes a run doc; if not, caller can source from our DB
    return {}
