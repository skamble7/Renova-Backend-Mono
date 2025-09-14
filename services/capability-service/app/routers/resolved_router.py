from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import ResolvedPackView
from app.services import PackService

router = APIRouter(prefix="/capability/packs", tags=["packs"])
svc = PackService()


@router.get("/{pack_id}/resolved", response_model=ResolvedPackView)
async def resolved_view(pack_id: str):
    view = await svc.resolved_view(pack_id)
    if not view:
        raise HTTPException(status_code=404, detail="Pack not found")
    return view
