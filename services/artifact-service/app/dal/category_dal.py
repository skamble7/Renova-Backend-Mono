# services/artifact-service/app/dal/category_dal.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, ReturnDocument

from app.models.category import CategoryCreate, CategoryUpdate, CategoryDoc

COL = "cam_categories"

async def ensure_indexes(db: AsyncIOMotorDatabase):
    col = db[COL]
    # Unique key for category (e.g., diagram, pat, dam, ...)
    await col.create_index([("key", ASCENDING)], unique=True)
    # Name index for quick lookups
    await col.create_index([("name", ASCENDING)], unique=False)

async def upsert_category(db: AsyncIOMotorDatabase, body: CategoryCreate) -> CategoryDoc:
    now = datetime.utcnow()
    col = db[COL]
    res = await col.find_one_and_update(
        {"key": body.key},
        {
            "$set": {
                "key": body.key,
                "name": body.name,
                "description": body.description,
                "icon_svg": body.icon_svg,
                "updated_at": now,
            },
            "$setOnInsert": {"_id": str(uuid.uuid4()), "created_at": now},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return CategoryDoc(**res)

async def get_category(db: AsyncIOMotorDatabase, key: str) -> Optional[CategoryDoc]:
    d = await db[COL].find_one({"key": key})
    return CategoryDoc(**d) if d else None

async def list_categories(
    db: AsyncIOMotorDatabase,
    *,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    col = db[COL]
    query: Dict[str, Any] = {}
    if q:
        query = {"$or": [{"key": {"$regex": q, "$options": "i"}}, {"name": {"$regex": q, "$options": "i"}}]}
    cur = col.find(query).sort("key", ASCENDING).skip(max(0, offset)).limit(min(limit, 200))
    return [d async for d in cur]

async def update_category(db: AsyncIOMotorDatabase, key: str, body: CategoryUpdate) -> Optional[CategoryDoc]:
    now = datetime.utcnow()
    updates: Dict[str, Any] = {"updated_at": now}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.icon_svg is not None:
        updates["icon_svg"] = body.icon_svg

    res = await db[COL].find_one_and_update(
        {"key": key},
        {"$set": updates},
        return_document=ReturnDocument.AFTER,
    )
    return CategoryDoc(**res) if res else None

async def delete_category(db: AsyncIOMotorDatabase, key: str) -> bool:
    res = await db[COL].delete_one({"key": key})
    return res.deleted_count == 1

# ─────────────────────────────────────────────────────────────
# NEW: bulk fetch by keys (preserve request order; skip missing)
# ─────────────────────────────────────────────────────────────
async def get_categories_by_keys(db: AsyncIOMotorDatabase, keys: List[str]) -> List[CategoryDoc]:
    if not keys:
        return []
    col = db[COL]
    docs = [d async for d in col.find({"key": {"$in": keys}})]
    by_key = {d["key"]: d for d in docs}
    ordered = [by_key[k] for k in keys if k in by_key]
    return [CategoryDoc(**d) for d in ordered]
