# services/artifact-service/app/seeds/seed_categories.py
from __future__ import annotations

from typing import Dict, List
from datetime import datetime

from app.dal.category_dal import ensure_indexes
from motor.motor_asyncio import AsyncIOMotorDatabase

CATEGORY_KEYS: List[str] = [
    # Generic CAM categories
    "diagram","contract","catalog","workflow","data","ops","asset",
    # Renova-specific
    "domain","code","mapping","cobol","jcl",
]

ICONS: Dict[str, str] = {
    "diagram": '<svg ...>...</svg>',  # same as Raina’s simple VS Code–friendly icons
    "contract": '<svg ...>...</svg>',
    "catalog": '<svg ...>...</svg>',
    "workflow": '<svg ...>...</svg>',
    "data": '<svg ...>...</svg>',
    "ops": '<svg ...>...</svg>',
    "asset": '<svg ...>...</svg>',
    "domain": '<svg ...>...</svg>',
    "code": '<svg ...>...</svg>',
    "mapping": '<svg ...>...</svg>',
    "cobol": '<svg ...>...</svg>',
    "jcl": '<svg ...>...</svg>',
}

def _build_doc(key: str, name: str, description: str, icon_svg: str) -> dict:
    now = datetime.utcnow()
    return {
        "_id": f"cat:{key}",
        "key": key,
        "name": name,
        "description": description,
        "icon_svg": icon_svg,
        "created_at": now,
        "updated_at": now,
    }

async def ensure_categories_seed(db: AsyncIOMotorDatabase) -> dict:
    await ensure_indexes(db)
    col = db["cam_categories"]

    existing_keys = {d["key"] async for d in col.find({}, {"key": 1, "_id": 0})}
    to_seed = [k for k in CATEGORY_KEYS if k not in existing_keys]

    seeded = 0
    for key in to_seed:
        name = key.title()
        desc = f"Category for CAM artifacts with key '{key}'."
        icon = ICONS.get(key, ICONS["diagram"])
        await col.insert_one(_build_doc(key, name, desc, icon))
        seeded += 1

    return {"existing": len(existing_keys), "seeded": seeded, "total": len(CATEGORY_KEYS)}
