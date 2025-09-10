from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, TEXT
from pymongo.errors import OperationFailure

from ..models.capability_pack import (
    CapabilityPack, CapabilityPackCreate, CapabilityPackUpdate,
    GlobalCapability, GlobalCapabilityCreate, GlobalCapabilityUpdate,
    CapabilitySnapshot, Playbook
)

PACKS = "capability_packs"
CAPS = "capabilities"

# ─────────────────────────────────────────────────────────────
# Indexes
# ─────────────────────────────────────────────────────────────
async def ensure_indexes(db: AsyncIOMotorDatabase):
    """
    Robust, idempotent index creation.

    PACKS:
      - unique (key, version)
      - text(title, description)

    CAPS (global capabilities):
      - unique(id)
      - text(name, description)
      - normal multikey index on tags
    """

    async def _index_info(col):
        info = await col.index_information()
        out = []
        for name, meta in info.items():
            keys = meta.get("key") or meta.get("key_pattern") or []
            out.append({
                "name": name,
                "keys": list(keys),
                "unique": bool(meta.get("unique", False)),
                "weights": meta.get("weights") or {},
            })
        return out

    def _same_keypattern(a: list, b: list) -> bool:
        return list(a) == list(b)

    async def _ensure_index(col, keys, *, name=None, unique=False, drop_if_conflict=False):
        existing = await _index_info(col)
        found = None
        for idx in existing:
            if _same_keypattern(idx["keys"], keys):
                found = idx
                break

        if found:
            if unique and not found["unique"]:
                if drop_if_conflict:
                    try:
                        await col.drop_index(found["name"])
                    except Exception:
                        pass
                else:
                    return
            else:
                return

        try:
            await col.create_index(keys, name=name, unique=unique)
        except OperationFailure as e:
            if e.code != 85:  # 85 = IndexOptionsConflict
                raise

    # ---------- PACKS ----------
    packs = db[PACKS]

    await _ensure_index(
        packs,
        [("key", ASCENDING), ("version", ASCENDING)],
        name="uniq_key_version",
        unique=True,
        drop_if_conflict=True,
    )

    try:
        await packs.create_index([("title", TEXT), ("description", TEXT)], name="packs_text")
    except OperationFailure as e:
        if e.code != 85:
            raise

    # ---------- CAPS ----------
    caps_col = db[CAPS]

    # Drop ANY existing text index (Mongo allows only one per collection)
    info = await caps_col.index_information()
    for idx_name, meta in info.items():
        if meta.get("weights") or ("textIndexVersion" in meta):
            try:
                await caps_col.drop_index(idx_name)
            except Exception:
                pass

    await _ensure_index(
        caps_col,
        [("id", ASCENDING)],
        name="uniq_id",
        unique=True,
        drop_if_conflict=True,
    )

    try:
        await caps_col.create_index([("name", TEXT), ("description", TEXT)], name="caps_text")
    except OperationFailure as e:
        if e.code != 85:
            raise

    await _ensure_index(caps_col, [("tags", ASCENDING)], name="caps_tags")


# ─────────────────────────────────────────────────────────────
# Global Capabilities CRUD
# ─────────────────────────────────────────────────────────────
async def create_global_capability(db: AsyncIOMotorDatabase, body: GlobalCapabilityCreate) -> GlobalCapability:
    doc = body.model_dump()
    await db[CAPS].insert_one(doc)
    return GlobalCapability(**doc)

async def get_global_capability(db: AsyncIOMotorDatabase, cap_id: str) -> Optional[GlobalCapability]:
    d = await db[CAPS].find_one({"id": cap_id}, projection={"_id": False})
    return GlobalCapability(**d) if d else None

async def list_global_capabilities(
    db: AsyncIOMotorDatabase,
    q: Optional[str],
    tag: Optional[str],
    limit: int,
    offset: int,
) -> List[dict]:
    query: Dict[str, Any] = {}
    if q:
        query["$text"] = {"$search": q}
    if tag:
        query["tags"] = tag
    # NOTE: project out _id to avoid ObjectId serialization issues
    cur = (
        db[CAPS]
        .find(query, projection={"_id": False})
        .sort([("id", 1)])
        .skip(offset)
        .limit(min(limit, 200))
    )
    return [d async for d in cur]

async def update_global_capability(db: AsyncIOMotorDatabase, cap_id: str, patch: GlobalCapabilityUpdate) -> Optional[GlobalCapability]:
    update = {k: v for k, v in patch.model_dump(exclude_none=True).items()}
    d = await db[CAPS].find_one_and_update(
        {"id": cap_id}, {"$set": update}, return_document=True, projection={"_id": False}
    )
    return GlobalCapability(**d) if d else None

async def delete_global_capability(db: AsyncIOMotorDatabase, cap_id: str) -> bool:
    res = await db[CAPS].delete_one({"id": cap_id})
    return res.deleted_count == 1


# ─────────────────────────────────────────────────────────────
# Capability Pack CRUD
# ─────────────────────────────────────────────────────────────
async def create_pack(db: AsyncIOMotorDatabase, body: CapabilityPackCreate, snapshots: List[CapabilitySnapshot]) -> CapabilityPack:
    now = datetime.utcnow()
    doc = {
        "_id": str(uuid.uuid4()),
        "key": body.key,
        "version": body.version,
        "title": body.title,
        "description": body.description,
        "capability_ids": list(body.capability_ids),
        "capabilities": [s.model_dump() for s in snapshots],
        "playbooks": [p.model_dump() for p in body.playbooks],
        # NEW: persist optional fields for hybrid packs
        "connectors": list(getattr(body, "connectors", []) or []),
        "tools": list(getattr(body, "tools", []) or []),
        "default_policies": dict(getattr(body, "default_policies", {}) or {}),
        "created_at": now,
        "updated_at": now,
    }
    await db[PACKS].insert_one(doc)
    return CapabilityPack(**doc)


async def get_pack(db: AsyncIOMotorDatabase, key: str, version: str) -> Optional[CapabilityPack]:
    # Keep _id; CapabilityPack expects it (alias "_id")
    d = await db[PACKS].find_one({"key": key, "version": version})
    return CapabilityPack(**d) if d else None

async def list_packs(db: AsyncIOMotorDatabase, key: Optional[str], q: Optional[str], limit: int, offset: int) -> List[dict]:
    query: Dict[str, Any] = {}
    if key:
        query["key"] = key
    if q:
        query["$text"] = {"$search": q}
    # Keep _id (string UUID in our writes; safe to serialize/validate)
    cur = (
        db[PACKS]
        .find(query)
        .sort([("updated_at", -1)])
        .skip(offset)
        .limit(min(limit, 200))
    )
    return [d async for d in cur]

async def upsert_pack(db: AsyncIOMotorDatabase, key: str, version: str, patch: CapabilityPackUpdate) -> Optional[CapabilityPack]:
    now = datetime.utcnow()
    update = {k: v for k, v in patch.model_dump(exclude_none=True).items()}
    update["updated_at"] = now
    d = await db[PACKS].find_one_and_update(
        {"key": key, "version": version},
        {"$set": update},
        upsert=False,
        return_document=True,
    )
    return CapabilityPack(**d) if d else None

async def delete_pack(db: AsyncIOMotorDatabase, key: str, version: str) -> bool:
    res = await db[PACKS].delete_one({"key": key, "version": version})
    return res.deleted_count == 1


# ─────────────────────────────────────────────────────────────
# Pack: capability linking / snapshotting
# ─────────────────────────────────────────────────────────────
async def load_capability_snapshots(db: AsyncIOMotorDatabase, cap_ids: List[str]) -> List[CapabilitySnapshot]:
    if not cap_ids:
        return []
    cur = db[CAPS].find({"id": {"$in": cap_ids}}, projection={"_id": False})
    by_id: Dict[str, GlobalCapability] = {d["id"]: GlobalCapability(**d) async for d in cur}
    snapshots: List[CapabilitySnapshot] = []
    for cid in cap_ids:
        g = by_id.get(cid)
        if not g:
            continue
        snapshots.append(CapabilitySnapshot(
            id=g.id, name=g.name, description=g.description, tags=g.tags,
            parameters_schema=g.parameters_schema, produces_kinds=g.produces_kinds, agent=g.agent
        ))
    return snapshots

async def set_pack_capabilities(db: AsyncIOMotorDatabase, key: str, version: str, cap_ids: List[str]) -> Optional[CapabilityPack]:
    snaps = await load_capability_snapshots(db, cap_ids)
    now = datetime.utcnow()
    d = await db[PACKS].find_one_and_update(
        {"key": key, "version": version},
        {"$set": {"capability_ids": cap_ids, "capabilities": [s.model_dump() for s in snaps], "updated_at": now}},
        return_document=True,
    )
    return CapabilityPack(**d) if d else None


# ─────────────────────────────────────────────────────────────
# Pack: playbook / steps helpers
# ─────────────────────────────────────────────────────────────
async def add_playbook(db: AsyncIOMotorDatabase, key: str, version: str, pb: Playbook) -> Optional[CapabilityPack]:
    now = datetime.utcnow()
    d = await db[PACKS].find_one_and_update(
        {"key": key, "version": version},
        {"$push": {"playbooks": pb.model_dump()}, "$set": {"updated_at": now}},
        return_document=True,
    )
    return CapabilityPack(**d) if d else None

async def remove_playbook(db: AsyncIOMotorDatabase, key: str, version: str, playbook_id: str) -> Optional[CapabilityPack]:
    now = datetime.utcnow()
    d = await db[PACKS].find_one_and_update(
        {"key": key, "version": version},
        {"$pull": {"playbooks": {"id": playbook_id}}, "$set": {"updated_at": now}},
        return_document=True,
    )
    return CapabilityPack(**d) if d else None

async def replace_playbooks(db: AsyncIOMotorDatabase, key: str, version: str, playbooks: List[Playbook]) -> Optional[CapabilityPack]:
    now = datetime.utcnow()
    d = await db[PACKS].find_one_and_update(
        {"key": key, "version": version},
        {"$set": {"playbooks": [p.model_dump() for p in playbooks], "updated_at": now}},
        return_document=True,
    )
    return CapabilityPack(**d) if d else None
