# services/artifact-service/app/seeds/bootstrap.py
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, Any, Set, List

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.dal.kind_registry_dal import KINDS, upsert_kind, ensure_registry_indexes
from app.seeds.seed_registry import KIND_DOCS  # new: single source of truth
from app.seeds.seed_categories import ensure_categories_seed

log = logging.getLogger(__name__)


def _kind_ids(docs: List[Dict[str, Any]]) -> List[str]:
    return [d["_id"] for d in docs]


async def ensure_registry_seed(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    """
    Ensures all canonical kind documents from KIND_DOCS exist in the registry.
    - Keeps your previous semantics: only inserts missing kinds (no mass overwrite).
    - Adds created_at/updated_at if absent for cleanliness.
    """
    await ensure_registry_indexes(db)
    col = db[KINDS]

    existing: Set[str] = {d["_id"] async for d in col.find({}, {"_id": 1})}
    desired_ids = set(_kind_ids(KIND_DOCS))
    missing_ids = [k for k in desired_ids if k not in existing]

    # Insert only the missing ones to avoid surprising overwrites in prod
    seeded = 0
    now = datetime.utcnow()
    by_id: Dict[str, Dict[str, Any]] = {d["_id"]: d for d in KIND_DOCS}

    for kind_id in missing_ids:
        doc = dict(by_id[kind_id])  # shallow copy
        # Ensure common timestamps if not present
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        await upsert_kind(db, doc)
        seeded += 1

    mode = "fresh" if not existing else ("partial" if missing_ids else "skip")
    log.info(
        "Kind registry seed: mode=%s existing=%d seeded=%d (desired_total=%d)",
        mode, len(existing), seeded, len(desired_ids)
    )
    return {"mode": mode, "existing": len(existing), "seeded": seeded, "desired": len(desired_ids)}


async def ensure_all_seeds(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    kinds_meta = await ensure_registry_seed(db)
    cats_meta = await ensure_categories_seed(db)
    return {"kinds": kinds_meta, "categories": cats_meta}
