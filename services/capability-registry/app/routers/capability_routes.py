# services/capability-registry/app/routers/capability_routes.py
from __future__ import annotations

from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Response, status, Depends
from fastapi.responses import ORJSONResponse
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import ValidationError

try:
    from bson import ObjectId as _BsonObjectId  # type: ignore
except Exception:  # pragma: no cover
    _BsonObjectId = tuple()  # fallback so isinstance checks won't crash

from ..config import settings
from ..db.mongodb import get_db
from ..events.rabbit import publish_event_v1
from ..services.artifact_registry_client import ArtifactRegistryClient
from ..dal import capability_dal as dal
from ..models.capability_pack import (
    CapabilityPackCreate, CapabilityPackUpdate, CapabilityPack, Playbook,
    GlobalCapabilityCreate, GlobalCapabilityUpdate, GlobalCapability
)

router = APIRouter(
    prefix="/capability",
    tags=["capability"],
    default_response_class=ORJSONResponse,
)

def _org() -> str:
    return settings.events_org

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
async def _validate_produces_kinds(kind_ids: List[str], client: ArtifactRegistryClient):
    if not kind_ids:
        return
    valid, invalid = await client.validate_kinds(kind_ids)
    if invalid:
        raise HTTPException(
            status_code=422,
            detail={"error": "Invalid produces_kinds", "invalid": invalid, "valid": valid},
        )

def _validate_pack_shape_like_spec(pack: CapabilityPack):
    """
    Strict validation for write-paths only (create/update/etc).
    - capability steps must reference an id in pack.capability_ids
    - tool_call steps must reference a key in pack.tools
    - edges and depends_on_steps must reference valid step ids
    """
    if not pack.capability_ids:
        raise HTTPException(status_code=422, detail="Pack must include at least one capability")
    if not pack.playbooks:
        raise HTTPException(status_code=422, detail="Pack must include at least one playbook")

    capset = set(pack.capability_ids or [])
    toolset = set(pack.tools or [])

    for pb in pack.playbooks or []:
        if not pb.steps:
            raise HTTPException(status_code=422, detail=f"Playbook '{pb.id}' must include at least one step")

        step_ids = {st.id for st in pb.steps}
        if len(step_ids) != len(pb.steps):
            raise HTTPException(status_code=422, detail=f"Playbook '{pb.id}' has duplicate step ids")

        for st in pb.steps:
            st_type = getattr(st, "type", None)
            if st_type == "capability":
                cap_id = getattr(st, "capability_id", None)
                if not cap_id:
                    raise HTTPException(status_code=422, detail=f"Capability step '{st.id}' missing capability_id")
                if cap_id not in capset:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Capability step '{st.id}' references unknown capability_id '{cap_id}'"
                    )
            elif st_type == "tool_call":
                tool_key = getattr(st, "tool_key", None)
                if not tool_key:
                    raise HTTPException(status_code=422, detail=f"Tool step '{st.id}' missing tool_key")
                if tool_key not in toolset:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Tool step '{st.id}' references tool_key '{tool_key}' not present in pack.tools"
                    )
            else:
                raise HTTPException(status_code=422, detail=f"Unknown step type '{st_type}' in step '{st.id}'")

            # depends_on_steps must reference steps in this playbook
            for dep in getattr(st, "depends_on_steps", []) or []:
                if dep not in step_ids:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Step '{st.id}' depends on unknown step id '{dep}' in playbook '{pb.id}'"
                    )

        # edges must reference known step ids
        for e in (pb.edges or []):
            frm, to = e.get("from"), e.get("to")
            if frm not in step_ids or to not in step_ids:
                raise HTTPException(
                    status_code=422,
                    detail=f"Edge refers to unknown step ids: from='{frm}' to='{to}' in playbook '{pb.id}'"
                )


def _pack_doc_to_model(d: Dict[str, Any]) -> CapabilityPack:
    """
    Make legacy documents safe:
      - ensure '_id' exists and is a string (coerce ObjectId -> str)
      - if truly missing, synthesize a deterministic surrogate from key+version
    """
    data = dict(d)
    if "_id" not in data or data["_id"] is None:
        data["_id"] = f"{data.get('key', 'unknown')}::{data.get('version', 'unknown')}"
    else:
        try:
            if isinstance(data["_id"], _BsonObjectId):
                data["_id"] = str(data["_id"])
        except Exception:
            data["_id"] = str(data["_id"])
    return CapabilityPack(**data)

# ─────────────────────────────────────────────────────────────
# CAPABILITY PACKS — static before any /{capability_id} route
# ─────────────────────────────────────────────────────────────
@router.get("/packs", response_model=List[CapabilityPack])
async def list_packs(
    q: str | None = Query(default=None, description="full-text search across title and description"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    docs = await dal.list_packs(db, key=None, q=q, limit=limit, offset=offset)
    return [_pack_doc_to_model(d) for d in docs]

@router.post("/pack", status_code=status.HTTP_201_CREATED, response_model=CapabilityPack)
async def create_pack(body: CapabilityPackCreate, db: AsyncIOMotorDatabase = Depends(get_db)):
    await dal.ensure_indexes(db)
    existing = await dal.get_pack(db, body.key, body.version)
    if existing:
        raise HTTPException(status_code=409, detail="Capability pack with key+version exists")

    snaps = await dal.load_capability_snapshots(db, body.capability_ids)
    if len(snaps) != len(set(body.capability_ids)):
        missing = set(body.capability_ids) - {s.id for s in snaps}
        raise HTTPException(status_code=422, detail={"error": "Unknown capability_ids", "missing": sorted(missing)})

    pack = await dal.create_pack(db, body, snaps)
    _validate_pack_shape_like_spec(pack)
    publish_event_v1(org=_org(), event="pack.created", payload={"key": pack.key, "version": pack.version})
    return pack

@router.get("/pack/{key}/{version}", response_model=CapabilityPack)
async def get_pack(key: str, version: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    try:
        pack = await dal.get_pack(db, key, version)
        if not pack:
            raise HTTPException(status_code=404, detail="Not found")
        return pack
    except ValidationError:
        raw = await db["capability_packs"].find_one({"key": key, "version": version})
        if not raw:
            raise HTTPException(status_code=404, detail="Not found")
        return _pack_doc_to_model(raw)

@router.put("/pack/{key}/{version}", response_model=CapabilityPack)
async def update_pack(key: str, version: str, body: CapabilityPackUpdate, db: AsyncIOMotorDatabase = Depends(get_db)):
    if body.capability_ids is not None:
        snaps = await dal.load_capability_snapshots(db, body.capability_ids)
        if len(snaps) != len(set(body.capability_ids)):
            missing = set(body.capability_ids) - {s.id for s in snaps}
            raise HTTPException(status_code=422, detail={"error": "Unknown capability_ids", "missing": sorted(missing)})
        body_dict = body.model_dump(exclude_none=True)
        body_dict["capabilities"] = [s.model_dump() for s in snaps]
        body = CapabilityPackUpdate(**body_dict)

    try:
        pack = await dal.upsert_pack(db, key, version, body)
        if not pack:
            raise HTTPException(status_code=404, detail="Not found")
    except ValidationError:
        raw = await db["capability_packs"].find_one({"key": key, "version": version})
        if not raw:
            raise HTTPException(status_code=404, detail="Not found")
        pack = _pack_doc_to_model(raw)

    _validate_pack_shape_like_spec(pack)
    publish_event_v1(org=_org(), event="pack.updated", payload={"key": key, "version": version})
    return pack

@router.delete("/pack/{key}/{version}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pack(key: str, version: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    ok = await dal.delete_pack(db, key, version)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    publish_event_v1(org=_org(), event="pack.deleted", payload={"key": key, "version": version})
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/pack/{key}/{version}/playbooks", response_model=List[Playbook])
async def list_playbooks(key: str, version: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    try:
        pack = await dal.get_pack(db, key, version)
        if not pack:
            raise HTTPException(status_code=404, detail="Not found")
        return pack.playbooks
    except ValidationError:
        raw = await db["capability_packs"].find_one({"key": key, "version": version})
        if not raw:
            raise HTTPException(status_code=404, detail="Not found")
        pack = _pack_doc_to_model(raw)
        return pack.playbooks

@router.put("/pack/{key}/{version}/capabilities", response_model=CapabilityPack)
async def set_pack_capabilities(key: str, version: str, payload: Dict[str, List[str]], db: AsyncIOMotorDatabase = Depends(get_db)):
    cap_ids = payload.get("capability_ids", [])
    if not isinstance(cap_ids, list) or not cap_ids:
        raise HTTPException(status_code=400, detail="Body must contain non-empty 'capability_ids' list")

    try:
        pack = await dal.set_pack_capabilities(db, key, version, cap_ids)
        if not pack:
            raise HTTPException(status_code=404, detail="Not found")
    except ValidationError:
        raw = await db["capability_packs"].find_one({"key": key, "version": version})
        if not raw:
            raise HTTPException(status_code=404, detail="Not found")
        pack = _pack_doc_to_model(raw)

    _validate_pack_shape_like_spec(pack)
    publish_event_v1(org=_org(), event="pack.capabilities.set", payload={"key": key, "version": version, "count": len(cap_ids)})
    return pack

@router.post("/pack/{key}/{version}/playbooks", response_model=CapabilityPack, status_code=status.HTTP_201_CREATED)
async def add_playbook(key: str, version: str, body: Playbook, db: AsyncIOMotorDatabase = Depends(get_db)):
    try:
        pack = await dal.add_playbook(db, key, version, body)
        if not pack:
            raise HTTPException(status_code=404, detail="Not found")
    except ValidationError:
        raw = await db["capability_packs"].find_one({"key": key, "version": version})
        if not raw:
            raise HTTPException(status_code=404, detail="Not found")
        pack = _pack_doc_to_model(raw)

    _validate_pack_shape_like_spec(pack)
    publish_event_v1(org=_org(), event="pack.playbook.added", payload={"key": key, "version": version, "playbook_id": body.id})
    return pack

@router.delete("/pack/{key}/{version}/playbooks/{playbook_id}", response_model=CapabilityPack)
async def remove_playbook(key: str, version: str, playbook_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    try:
        pack = await dal.remove_playbook(db, key, version, playbook_id)
        if not pack:
            raise HTTPException(status_code=404, detail="Not found")
    except ValidationError:
        raw = await db["capability_packs"].find_one({"key": key, "version": version})
        if not raw:
            raise HTTPException(status_code=404, detail="Not found")
        pack = _pack_doc_to_model(raw)

    # Allow empty playbooks after deletion; don't enforce here.
    publish_event_v1(org=_org(), event="pack.playbook.removed", payload={"key": key, "version": version, "playbook_id": playbook_id})
    return pack

@router.put("/pack/{key}/{version}/playbooks/reorder", response_model=CapabilityPack)
async def reorder_steps(
    key: str,
    version: str,
    body: Dict[str, Any],
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    playbook_id = body.get("playbook_id")
    order: List[str] = body.get("order") or []
    if not playbook_id or not order:
        raise HTTPException(status_code=400, detail="Body must include 'playbook_id' and non-empty 'order' list")

    try:
        pack = await dal.get_pack(db, key, version)
        if not pack:
            raise HTTPException(status_code=404, detail="Not found")
    except ValidationError:
        raw = await db["capability_packs"].find_one({"key": key, "version": version})
        if not raw:
            raise HTTPException(status_code=404, detail="Not found")
        pack = _pack_doc_to_model(raw)

    new_pbs: List[Playbook] = []
    target_found = False
    for pb in pack.playbooks:
        if pb.id != playbook_id:
            new_pbs.append(pb)
            continue
        target_found = True
        steps_by_id = {s.id: s for s in pb.steps}
        if set(order) != set(steps_by_id.keys()):
            raise HTTPException(status_code=422, detail="Order must contain exactly the same step ids")
        reordered = [steps_by_id[sid] for sid in order]
        new_pbs.append(Playbook(
            id=pb.id, name=pb.name, description=pb.description,
            steps=reordered, edges=pb.edges, produces=pb.produces
        ))

    if not target_found:
        raise HTTPException(status_code=404, detail=f"Playbook '{playbook_id}' not found")

    try:
        pack = await dal.replace_playbooks(db, key, version, new_pbs)
    except ValidationError:
        raw = await db["capability_packs"].find_one({"key": key, "version": version})
        if not raw:
            raise HTTPException(status_code=404, detail="Not found")
        pack = _pack_doc_to_model(raw)

    _validate_pack_shape_like_spec(pack)
    publish_event_v1(org=_org(), event="pack.playbook.reordered", payload={"key": key, "version": version, "playbook_id": playbook_id})
    return pack

# ─────────────────────────────────────────────────────────────
# GLOBAL CAPABILITIES — static routes before dynamic
# ─────────────────────────────────────────────────────────────
@router.get("/list/all")
async def list_capabilities(
    q: Optional[str] = Query(None, description="full-text search on name/description"),
    tag: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    items = await dal.list_global_capabilities(db, q, tag, limit, offset)
    return {"items": items, "count": len(items)}

@router.post("", status_code=status.HTTP_201_CREATED, response_model=GlobalCapability)
async def create_capability(body: GlobalCapabilityCreate, db: AsyncIOMotorDatabase = Depends(get_db)):
    await dal.ensure_indexes(db)
    existing = await dal.get_global_capability(db, body.id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Capability '{body.id}' already exists")
    client = ArtifactRegistryClient()
    await _validate_produces_kinds(body.produces_kinds or [], client)
    cap = await dal.create_global_capability(db, body)
    publish_event_v1(org=_org(), event="capability.created", payload={"id": cap.id})
    return cap

@router.put("/{capability_id}", response_model=GlobalCapability)
async def update_capability(capability_id: str, body: GlobalCapabilityUpdate, db: AsyncIOMotorDatabase = Depends(get_db)):
    if body.produces_kinds is not None:
        client = ArtifactRegistryClient()
        await _validate_produces_kinds(body.produces_kinds, client)
    cap = await dal.update_global_capability(db, capability_id, body)
    if not cap:
        raise HTTPException(status_code=404, detail="Not found")
    publish_event_v1(org=_org(), event="capability.updated", payload={"id": capability_id})
    return cap

@router.delete("/{capability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_capability(capability_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    ok = await dal.delete_global_capability(db, capability_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Not found")
    publish_event_v1(org=_org(), event="capability.deleted", payload={"id": capability_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)

@router.get("/{capability_id}", response_model=GlobalCapability)
async def get_capability(capability_id: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    # IMPORTANT: this dynamic route is last so it won't shadow /packs etc.
    cap = await dal.get_global_capability(db, capability_id)
    if not cap:
        raise HTTPException(status_code=404, detail="Not found")
    return cap
