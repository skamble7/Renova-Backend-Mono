from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Path, Request

from app.clients.capability_service import CapabilityServiceClient, ServiceClientError

router = APIRouter(prefix="/packs", tags=["packs"])


@router.get("/{pack_id}")
async def get_pack(
    request: Request,
    pack_id: str = Path(..., description="Pack id in the form key@version (e.g., cobol-mainframe@v1.0)"),
) -> Dict[str, Any]:
    """
    Passthrough to capability-service: GET /capability/packs/{pack_id}
    """
    correlation_id = request.headers.get("X-Correlation-ID")
    try:
        async with CapabilityServiceClient() as caps:
            return await caps.get_pack(pack_id, correlation_id=correlation_id)
    except ServiceClientError as sce:
        raise HTTPException(status_code=sce.status, detail=f"capability-service error: {sce.body}") from sce
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/{pack_id}/resolved")
async def get_resolved_pack(
    request: Request,
    pack_id: str = Path(..., description="Pack id in the form key@version (e.g., cobol-mainframe@v1.0)"),
) -> Dict[str, Any]:
    """
    Passthrough to capability-service: GET /capability/packs/{pack_id}/resolved
    """
    correlation_id = request.headers.get("X-Correlation-ID")
    try:
        async with CapabilityServiceClient() as caps:
            return await caps.get_resolved_pack(pack_id, correlation_id=correlation_id)
    except ServiceClientError as sce:
        raise HTTPException(status_code=sce.status, detail=f"capability-service error: {sce.body}") from sce
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
