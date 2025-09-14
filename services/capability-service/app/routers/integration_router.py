from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.models import MCPIntegration
from app.services import IntegrationService

router = APIRouter(prefix="/integration", tags=["integrations"])
svc = IntegrationService()


@router.post("/", response_model=MCPIntegration)
async def create_integration(payload: MCPIntegration, actor: Optional[str] = None):
    return await svc.create(payload, actor=actor)


@router.get("/{integration_id}", response_model=MCPIntegration)
async def get_integration(integration_id: str):
    integ = await svc.get(integration_id)
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integ


@router.put("/{integration_id}", response_model=MCPIntegration)
async def update_integration(integration_id: str, patch: Dict[str, Any], actor: Optional[str] = None):
    integ = await svc.update(integration_id, patch, actor=actor)
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integ


@router.delete("/{integration_id}")
async def delete_integration(integration_id: str, actor: Optional[str] = None):
    ok = await svc.delete(integration_id, actor=actor)
    if not ok:
        raise HTTPException(status_code=404, detail="Integration not found")
    return {"deleted": True}


@router.get("", response_model=List[MCPIntegration])
async def list_integrations(
    q: Optional[str] = Query(default=None),
    tag: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, _ = await svc.search(q=q, tag=tag, limit=limit, offset=offset)
    return items
