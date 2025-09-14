from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ReturnDocument

from app.db.mongo import get_db
from app.models import (
    CapabilityPack,
    CapabilityPackCreate,
    CapabilityPackUpdate,
    PackStatus,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strip_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _pack_id_from_key_version(key: str, version: str) -> str:
    # Stable, human-friendly primary key
    return f"{key}@{version}"


class PackDAL:
    """
    CRUD for CapabilityPack.
    Collection: 'capability_packs'
    """

    def __init__(self):
        self.col = get_db().capability_packs

    async def create(self, payload: CapabilityPackCreate, *, created_by: Optional[str] = None) -> CapabilityPack:
        _id = _pack_id_from_key_version(payload.key, payload.version)
        base_doc = {
            "_id": _id,
            "key": payload.key,
            "version": payload.version,
            "title": payload.title,
            "description": payload.description,
            "capability_ids": payload.capability_ids or [],
            "capabilities": [],  # snapshots will be injected by service layer
            "playbooks": [pb.model_dump() for pb in (payload.playbooks or [])],
            "status": PackStatus.draft.value,
            "created_at": _utcnow(),
            "updated_at": _utcnow(),
            "published_at": None,
            "created_by": created_by,
            "updated_by": created_by,
        }
        await self.col.insert_one(base_doc)
        return CapabilityPack.model_validate(base_doc)

    async def get(self, pack_id: str) -> Optional[CapabilityPack]:
        doc = await self.col.find_one({"_id": pack_id})
        return CapabilityPack.model_validate(doc) if doc else None

    async def get_by_key_version(self, key: str, version: str) -> Optional[CapabilityPack]:
        pack_id = _pack_id_from_key_version(key, version)
        return await self.get(pack_id)

    async def delete(self, pack_id: str) -> bool:
        res = await self.col.delete_one({"_id": pack_id})
        return res.deleted_count == 1

    async def update(self, pack_id: str, patch: CapabilityPackUpdate, *, updated_by: Optional[str] = None) -> Optional[CapabilityPack]:
        update_dict = _strip_none(patch.model_dump())
        if updated_by is not None:
            update_dict["updated_by"] = updated_by
        update_doc = {"$set": {**update_dict, "updated_at": _utcnow()}}
        doc = await self.col.find_one_and_update(
            {"_id": pack_id},
            update_doc,
            return_document=ReturnDocument.AFTER,
        )
        return CapabilityPack.model_validate(doc) if doc else None

    async def set_capability_snapshots(self, pack_id: str, snapshots: List[Dict[str, Any]]) -> Optional[CapabilityPack]:
        """
        Service layer should build 'snapshots' (CapabilitySnapshot dicts).
        This DAL method just persists them.
        """
        doc = await self.col.find_one_and_update(
            {"_id": pack_id},
            {"$set": {"capabilities": snapshots, "updated_at": _utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        return CapabilityPack.model_validate(doc) if doc else None

    async def publish(self, pack_id: str) -> Optional[CapabilityPack]:
        """
        Set status=published and stamp published_at (idempotent if already published).
        No immutability enforcement here—leave that to the service/router layer.
        """
        doc = await self.col.find_one({"_id": pack_id})
        if not doc:
            return None

        if doc.get("status") == PackStatus.published.value and doc.get("published_at"):
            # Already published; still return the model for convenience
            return CapabilityPack.model_validate(doc)

        upd = {
            "$set": {
                "status": PackStatus.published.value,
                "published_at": _utcnow(),
                "updated_at": _utcnow(),
            }
        }
        doc = await self.col.find_one_and_update(
            {"_id": pack_id},
            upd,
            return_document=ReturnDocument.AFTER,
        )
        return CapabilityPack.model_validate(doc) if doc else None

    async def search(
        self,
        *,
        key: Optional[str] = None,
        version: Optional[str] = None,
        status: Optional[PackStatus] = None,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[CapabilityPack], int]:
        filt: Dict[str, Any] = {}
        if key:
            filt["key"] = key
        if version:
            filt["version"] = version
        if status:
            filt["status"] = status.value if isinstance(status, PackStatus) else status
        if q:
            filt["$text"] = {"$search": q}

        total = await self.col.count_documents(filt)
        cursor = (
            self.col.find(filt)
            .sort([("key", 1), ("version", 1)])
            .skip(max(offset, 0))
            .limit(max(min(limit, 200), 1))
        )
        items = [CapabilityPack.model_validate(d) async for d in cursor]
        return items, total

    async def list_versions(self, key: str) -> List[str]:
        cursor = self.col.find({"key": key}, {"version": 1, "_id": 0}).sort("version", 1)
        return [d["version"] async for d in cursor]
