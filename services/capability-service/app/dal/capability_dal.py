from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ReturnDocument

from app.db.mongo import get_db
from app.models import GlobalCapability, GlobalCapabilityCreate, GlobalCapabilityUpdate


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strip_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class CapabilityDAL:
    """
    CRUD for GlobalCapability.
    Collection: 'capabilities'
    """

    def __init__(self):
        self.col = get_db().capabilities

    async def create(self, payload: GlobalCapabilityCreate) -> GlobalCapability:
        doc = GlobalCapability(
            **payload.model_dump(),
            created_at=_utcnow(),
            updated_at=_utcnow(),
        ).model_dump()
        await self.col.insert_one(doc)
        return GlobalCapability.model_validate(doc)

    async def get(self, capability_id: str) -> Optional[GlobalCapability]:
        doc = await self.col.find_one({"id": capability_id})
        return GlobalCapability.model_validate(doc) if doc else None

    async def delete(self, capability_id: str) -> bool:
        res = await self.col.delete_one({"id": capability_id})
        return res.deleted_count == 1

    async def update(self, capability_id: str, patch: GlobalCapabilityUpdate) -> Optional[GlobalCapability]:
        update_dict = _strip_none(patch.model_dump())
        if not update_dict:
            # No-op update; still update timestamp for idempotency if the doc exists
            update_dict = {}
        update_doc = {"$set": {**update_dict, "updated_at": _utcnow()}}
        doc = await self.col.find_one_and_update(
            {"id": capability_id},
            update_doc,
            return_document=ReturnDocument.AFTER,
        )
        return GlobalCapability.model_validate(doc) if doc else None

    async def search(
        self,
        *,
        tag: Optional[str] = None,
        produces_kind: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[GlobalCapability], int]:
        filt: Dict[str, Any] = {}
        if tag:
            filt["tags"] = tag
        if produces_kind:
            filt["produces_kinds"] = produces_kind
        if q:
            # simple contains on name/description
            filt["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
                {"id": {"$regex": q, "$options": "i"}},
            ]

        total = await self.col.count_documents(filt)
        cursor = (
            self.col.find(filt)
            .sort("id", 1)
            .skip(max(offset, 0))
            .limit(max(min(limit, 200), 1))
        )
        items = [GlobalCapability.model_validate(d) async for d in cursor]
        return items, total

    async def list_all_ids(self) -> List[str]:
        cursor = self.col.find({}, {"id": 1, "_id": 0}).sort("id", 1)
        return [d["id"] async for d in cursor]
