# services/learning-service/app/clients/parser_jcl.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import httpx
from app.config import settings

BASE = settings.PARSER_JCL_BASE_URL.rstrip("/")

async def parse(paths: Optional[List[str]] = None, sources: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Calls the JCL parser microservice.
    We send multiple commonly-used keys to be compatible with different implementations.
    Expected response (example):
      { "jobs":[{...}], "steps":[{...}], "items":[{"kind":"job","data":...}, ...] }
    """
    payload: Dict[str, Any] = {}
    if paths:
        payload["jcl_paths"] = paths
        payload["paths"] = paths     # lenient
    if sources:
        payload["sources"] = sources

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Common patterns: /v1/parse  (first)  or /v1/jcl/parse (fallback)
        for ep in ("/v1/parse", "/v1/jcl/parse"):
            url = f"{BASE}{ep}"
            try:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                return r.json() or {}
            except httpx.HTTPError:
                continue
    return {"jobs": [], "steps": []}
