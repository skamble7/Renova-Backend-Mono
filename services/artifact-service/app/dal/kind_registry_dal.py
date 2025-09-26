# services/artifact-service/app/dal/kind_registry_dal.py
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING

from ..models.kind_registry import (
    KindRegistryDoc,
    RegistryMetaDoc,
)

KINDS = "kind_registry"
KIND_PLUGINS = "kind_plugins"
REGISTRY_META = "registry_meta"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _canonical(obj: Dict[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────
# Indexes
# ─────────────────────────────────────────────────────────────

async def ensure_registry_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create indexes for the Kind Registry collections.

    NOTE:
    - Do NOT create an index on `_id` — MongoDB already maintains a unique `_id` index.
      Adding options like `unique=True` for `_id` causes error 197 (InvalidIndexSpecificationOption).
    """
    kinds = db[KINDS]
    # Fast lookups/filters
    await kinds.create_index([("aliases", ASCENDING)])   # multikey for alias lookup
    await kinds.create_index([("status", ASCENDING)])    # filter by status
    await kinds.create_index([("category", ASCENDING)])  # filter by category
    # Optional: query by diagram views/languages if needed in the future
    # (kept commented to avoid index bloat)
    # await kinds.create_index([("schema_versions.diagram_recipes.view", ASCENDING)])
    # await kinds.create_index([("schema_versions.diagram_recipes.language", ASCENDING)])

    plugins = db[KIND_PLUGINS]
    await plugins.create_index([("type", ASCENDING)])

    # REGISTRY_META uses the default _id index; no additional indexes needed.
    _ = db[REGISTRY_META]  # noqa: F841


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────

async def resolve_kind(db: AsyncIOMotorDatabase, kind_or_alias: str) -> Optional[KindRegistryDoc]:
    """
    Resolve a canonical kind by id or alias.
    """
    doc = await db[KINDS].find_one({"_id": kind_or_alias})
    if not doc:
        doc = await db[KINDS].find_one({"aliases": kind_or_alias})
    return KindRegistryDoc(**doc) if doc else None


async def get_kind(db: AsyncIOMotorDatabase, kind_id: str) -> Optional[KindRegistryDoc]:
    doc = await db[KINDS].find_one({"_id": kind_id})
    return KindRegistryDoc(**doc) if doc else None


async def list_kinds(
    db: AsyncIOMotorDatabase,
    *,
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    cond: Dict[str, Any] = {}
    if status:
        cond["status"] = status
    if category:
        cond["category"] = category

    cursor = (
        db[KINDS]
        .find(cond)
        .sort([("_id", 1)])
        .skip(max(0, offset))
        .limit(min(limit, 500))
    )
    return [d async for d in cursor]


async def get_schema_version_entry(
    db: AsyncIOMotorDatabase, kind_id: str, version: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Fetch a specific schema_version entry for a kind. If version is None, returns latest.
    """
    k = await get_kind(db, kind_id)
    if not k:
        return None
    target = version or k.latest_schema_version
    for entry in k.schema_versions:
        if entry.version == target:
            return entry.model_dump()
    return None


# ─────────────────────────────────────────────────────────────
# Diagram helpers (NEW)
# ─────────────────────────────────────────────────────────────

async def get_diagram_recipes(
    db: AsyncIOMotorDatabase,
    kind_id: str,
    version: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Return all diagram_recipes for the given kind/version.
    """
    entry = await get_schema_version_entry(db, kind_id, version)
    if not entry:
        return []
    return entry.get("diagram_recipes", []) or []


async def get_diagram_recipe(
    db: AsyncIOMotorDatabase,
    kind_id: str,
    *,
    version: Optional[str] = None,
    recipe_id: Optional[str] = None,
    view: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolve a single diagram recipe by id (preferred) or by view.
    If both are provided, id wins.
    """
    recipes = await get_diagram_recipes(db, kind_id, version)
    if not recipes:
        return None
    if recipe_id:
        for r in recipes:
            if r.get("id") == recipe_id:
                return r
        return None
    if view:
        # return first matching view
        for r in recipes:
            if r.get("view") == view:
                return r
        return None
    # neither id nor view specified
    return None


# ─────────────────────────────────────────────────────────────
# Writes (admin)
# ─────────────────────────────────────────────────────────────

async def upsert_kind(db: AsyncIOMotorDatabase, doc: Dict[str, Any]) -> KindRegistryDoc:
    """
    Admin-only: insert or replace a whole KindRegistryDoc (idempotent by _id).
    Also bumps registry meta etag/version.
    """
    now = datetime.utcnow()
    doc = {**doc, "updated_at": now}
    if "created_at" not in doc:
        doc["created_at"] = now

    await db[KINDS].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    await _bump_registry_meta(db)
    return KindRegistryDoc(**doc)


async def patch_kind(db: AsyncIOMotorDatabase, kind_id: str, patch: Dict[str, Any]) -> Optional[KindRegistryDoc]:
    """
    Admin-only: partial update of KindRegistryDoc.
    """
    now = datetime.utcnow()
    res = await db[KINDS].find_one_and_update(
        {"_id": kind_id},
        {"$set": {**patch, "updated_at": now}},
        return_document=True,
    )
    if not res:
        return None
    await _bump_registry_meta(db)
    return KindRegistryDoc(**res)


async def remove_kind(db: AsyncIOMotorDatabase, kind_id: str) -> bool:
    """
    Admin-only: delete kind definition (rare; prefer status=deprecated).
    """
    r = await db[KINDS].delete_one({"_id": kind_id})
    if r.deleted_count:
        await _bump_registry_meta(db)
        return True
    return False


# ─────────────────────────────────────────────────────────────
# Registry meta / ETag
# ─────────────────────────────────────────────────────────────

async def get_registry_meta(db: AsyncIOMotorDatabase) -> RegistryMetaDoc:
    d = await db[REGISTRY_META].find_one({"_id": "meta"})
    if d:
        return RegistryMetaDoc(**d)
    # initialize if missing
    etag = _sha256(_canonical({"seed": "empty"}))
    doc = RegistryMetaDoc(_id="meta", etag=etag, registry_version=1, updated_at=datetime.utcnow())
    await db[REGISTRY_META].insert_one(doc.model_dump(by_alias=True))
    return doc


async def _bump_registry_meta(db: AsyncIOMotorDatabase) -> RegistryMetaDoc:
    """
    Compute a new ETag (cheap approach: hash of timestamp + counter increment).
    """
    meta = await get_registry_meta(db)
    new_version = meta.registry_version + 1
    payload = {"v": new_version, "t": datetime.utcnow().isoformat()}
    new_etag = _sha256(_canonical(payload))

    res = await db[REGISTRY_META].find_one_and_update(
        {"_id": "meta"},
        {
            "$set": {"etag": new_etag, "updated_at": datetime.utcnow()},
            "$inc": {"registry_version": 1},
        },
        return_document=True,
    )
    return RegistryMetaDoc(**res)
