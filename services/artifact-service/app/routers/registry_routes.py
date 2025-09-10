# services/artifact-service/app/routers/registry_routes.py
from __future__ import annotations

from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.db.mongodb import get_db
from app.dal.kind_registry_dal import (
    ensure_registry_indexes,
    list_kinds,
    get_kind,
    upsert_kind,
    patch_kind,
    remove_kind,
    get_registry_meta,
)
from app.services.registry_service import KindRegistryService, SchemaValidationError

router = APIRouter(prefix="/registry", tags=["registry"])


# ─────────────────────────────────────────────────────────────
# Read APIs
# ─────────────────────────────────────────────────────────────
@router.get("/kinds")
async def api_list_kinds(
    status: Optional[str] = Query(None, pattern="^(active|deprecated)$"),
    category: Optional[str] = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    await ensure_registry_indexes(db)
    docs = await list_kinds(db, status=status, category=category, limit=limit, offset=offset)
    return {"items": docs, "count": len(docs)}


@router.get("/kinds/{kind_id}")
async def api_get_kind(
    kind_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await get_kind(db, kind_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Kind '{kind_id}' not found")
    return doc.model_dump(by_alias=True)


@router.get("/kinds/{kind_id}/prompt")
async def api_get_prompt(
    kind_id: str,
    version: Optional[str] = None,
    paradigm: Optional[str] = None,
    style: Optional[str] = None,
    format: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    svc = KindRegistryService(db)
    selectors: Dict[str, Any] = {}
    if paradigm:
        selectors["paradigm"] = paradigm
    if style:
        selectors["style"] = style
    if format:
        selectors["format"] = format

    out = await svc.select_prompt(kind_id, version=version, selectors=selectors)
    if not out:
        raise HTTPException(status_code=404, detail=f"Prompt not found for '{kind_id}'")
    return out


@router.post("/kinds/{kind_id}/adapt")
async def api_adapt_sample(
    kind_id: str,
    payload: Dict[str, Any],
    version: Optional[str] = None,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if not isinstance(payload, dict) or "data" not in payload:
        raise HTTPException(status_code=400, detail="Body must be an object with a 'data' field")
    svc = KindRegistryService(db)
    adapted = await svc.adapt_data(kind_id, payload["data"], version=version)
    return {"kind": kind_id, "version": version, "data": adapted}


@router.post("/validate")
async def api_validate(
    body: Dict[str, Any],
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    kind = body.get("kind")
    data = body.get("data")
    version = body.get("version")

    if not kind or not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Missing or invalid 'kind' or 'data'")

    svc = KindRegistryService(db)
    try:
        await svc.validate_data(kind, data, version=version)
    except SchemaValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True, "kind": kind, "version": version or "latest"}


@router.get("/meta")
async def api_registry_meta(
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    meta = await get_registry_meta(db)
    return meta.model_dump(by_alias=True)


# ─────────────────────────────────────────────────────────────
# Admin APIs
# ─────────────────────────────────────────────────────────────
@router.post("/kinds")
async def api_upsert_kind(
    body: Dict[str, Any],
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    if "_id" not in body:
        raise HTTPException(status_code=400, detail="Missing '_id' (canonical kind id)")
    doc = await upsert_kind(db, body)
    return doc.model_dump(by_alias=True)


@router.patch("/kinds/{kind_id}")
async def api_patch_kind(
    kind_id: str,
    patch: Dict[str, Any],
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    doc = await patch_kind(db, kind_id, patch)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Kind '{kind_id}' not found")
    return doc.model_dump(by_alias=True)


@router.delete("/kinds/{kind_id}")
async def api_delete_kind(
    kind_id: str,
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    ok = await remove_kind(db, kind_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Kind '{kind_id}' not found")
    return {"ok": True}

@router.post("/kinds/exists")
async def api_kinds_exists(
    body: Dict[str, List[str]],
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    ids = list(set(body.get("ids") or []))
    if not ids:
        return {"valid": [], "invalid": []}
    found = []
    for kid in ids:
        doc = await get_kind(db, kid)
        if doc:
            found.append(kid)
    valid = set(found)
    invalid = [k for k in ids if k not in valid]
    return {"valid": sorted(list(valid)), "invalid": sorted(invalid)}
