from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.models import CapabilityPack, CapabilityPackCreate, CapabilityPackUpdate, PackStatus
from app.services import PackService

router = APIRouter(prefix="/capability/packs", tags=["packs"])
svc = PackService()


@router.post("", response_model=CapabilityPack)
async def create_pack(payload: CapabilityPackCreate, actor: Optional[str] = None):
    return await svc.create(payload, actor=actor)


@router.get("", response_model=List[CapabilityPack])
async def list_packs(
    key: Optional[str] = Query(default=None),
    version: Optional[str] = Query(default=None),
    status: Optional[PackStatus] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    items, _ = await svc.search(key=key, version=version, status=status, q=q, limit=limit, offset=offset)
    return items


@router.get("/{pack_id}", response_model=CapabilityPack)
async def get_pack(pack_id: str):
    pack = await svc.get(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    return pack


@router.put("/{pack_id}", response_model=CapabilityPack)
async def update_pack(pack_id: str, patch: CapabilityPackUpdate, actor: Optional[str] = None):
    pack = await svc.update(pack_id, patch, actor=actor)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    return pack


@router.delete("/{pack_id}")
async def delete_pack(pack_id: str, actor: Optional[str] = None):
    ok = await svc.delete(pack_id, actor=actor)
    if not ok:
        raise HTTPException(status_code=404, detail="Pack not found")
    return {"deleted": True}


@router.post("/{pack_id}/refresh-snapshots", response_model=CapabilityPack)
async def refresh_snapshots(pack_id: str):
    pack = await svc.refresh_snapshots(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found")
    return pack


@router.post("/{pack_id}/publish", response_model=CapabilityPack)
async def publish_pack(pack_id: str, actor: Optional[str] = None):
    pack = await svc.publish(pack_id, actor=actor)
    if not pack:
        raise HTTPException(status_code=404, detail="Pack not found or not publishable")
    return pack
