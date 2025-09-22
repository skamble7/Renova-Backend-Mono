from __future__ import annotations

from fastapi import APIRouter, Query
from typing import Any, Dict

from app.db.mongo import get_db
from app.clients.capability_service import CapabilityServiceClient
from app.clients.artifact_service import ArtifactServiceClient

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health(deep: bool = Query(False, description="Run dependency checks")) -> Dict[str, Any]:
    """
    Liveness and (optionally) readiness probe.
    - If deep=true: pings Mongo, capability-service, and artifact-service.
    """
    status = "ok"
    details: Dict[str, Any] = {"service": "learning-service"}

    if not deep:
        return {"status": status, "details": details}

    # DB ping
    try:
        await get_db().command("ping")
        details["db"] = "ok"
    except Exception as e:
        status = "degraded"
        details["db"] = f"error: {e!r}"

    # capability-service health
    try:
        async with CapabilityServiceClient() as caps:
            caps_status = await caps.health()
        details["capability_service"] = caps_status
    except Exception as e:
        status = "degraded"
        details["capability_service"] = f"error: {e!r}"

    # artifact-service check (no explicit /health; use registry meta as a cheap probe)
    try:
        async with ArtifactServiceClient() as arts:
            meta = await arts._request("GET", "/registry/meta")  # lightweight, read-only
        details["artifact_service"] = {"meta": meta}
    except Exception as e:
        status = "degraded"
        details["artifact_service"] = f"error: {e!r}"

    return {"status": status, "details": details}
