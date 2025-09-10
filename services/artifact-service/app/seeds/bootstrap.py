# services/artifact-service/app/seeds/bootstrap.py
from __future__ import annotations

import logging
from typing import Dict, Any, Set

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.dal.kind_registry_dal import KINDS, upsert_kind, ensure_registry_indexes
from app.seeds.seed_registry import ALL_KINDS, build_kind_doc
from app.seeds.seed_categories import ensure_categories_seed

log = logging.getLogger(__name__)

async def ensure_registry_seed(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    await ensure_registry_indexes(db)
    col = db[KINDS]

    existing: Set[str] = {d["_id"] async for d in col.find({}, {"_id": 1})}
    missing = [k for k in ALL_KINDS if k not in existing]

    seeded = 0
    for k in missing:
        doc = build_kind_doc(k)
        await upsert_kind(db, doc)
        seeded += 1

    mode = "fresh" if not existing else ("partial" if missing else "skip")
    log.info("Kind registry seed: mode=%s existing=%d seeded=%d", mode, len(existing), seeded)
    return {"mode": mode, "existing": len(existing), "seeded": seeded}

async def ensure_all_seeds(db: AsyncIOMotorDatabase) -> Dict[str, Any]:
    kinds_meta = await ensure_registry_seed(db)
    cats_meta = await ensure_categories_seed(db)
    return {"kinds": kinds_meta, "categories": cats_meta}
