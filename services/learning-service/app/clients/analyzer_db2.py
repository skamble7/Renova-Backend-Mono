# services/learning-service/app/clients/analyzer_db2.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import httpx
from app.config import settings

BASE = settings.ANALYZER_DB2_BASE_URL.rstrip("/")

async def usage(program_paths: Optional[List[str]] = None, sources: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Calls the DB2 analyzer example service.
    Accepts either program file paths (preferred; shared landing zone) or raw sources.
    Expected response (example):
      { "items": [ { "program": "...", "tables": [{"name":"T1","ops":["SELECT","UPDATE"]}, ...] } ] }
    """
    payload: Dict[str, Any] = {}
    if program_paths:
        payload["program_paths"] = program_paths
        payload["paths"] = program_paths  # lenient
    if sources:
        payload["sources"] = sources

    async with httpx.AsyncClient(timeout=60.0) as client:
        for ep in ("/v1/usage", "/v1/db2/usage"):
            url = f"{BASE}{ep}"
            try:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                return r.json() or {}
            except httpx.HTTPError:
                continue
    return {"items": []}
