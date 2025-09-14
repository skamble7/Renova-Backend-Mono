from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pymongo import ReturnDocument

from app.db.mongo import get_db
from app.models import MCPIntegration


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _strip_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


class IntegrationDAL:
    """
    CRUD for MCPIntegration (reusable integrations registry).
    Collection: 'integrations'
    """

    def __init__(self):
        self.col = get_db().integrations

    async def create(self, integ: MCPIntegration) -> MCPIntegration:
        doc = integ.model_dump()
        # Ensure timestamps
        doc["created_at"] = doc.get("created_at") or _utcnow()
        doc["updated_at"] = _utcnow()
        await self.col.insert_one(doc)
        return MCPIntegration.model_validate(doc)

    async def get(self, integration_id: str) -> Optional[MCPIntegration]:
        doc = await self.col.find_one({"id": integration_id})
        return MCPIntegration.model_validate(doc) if doc else None

    async def delete(self, integration_id: str) -> bool:
        res = await self.col.delete_one({"id": integration_id})
        return res.deleted_count == 1

    async def update(self, integration_id: str, patch: Dict[str, Any]) -> Optional[MCPIntegration]:
        update_dict = _strip_none(patch)
        update_doc = {"$set": {**update_dict, "updated_at": _utcnow()}}
        doc = await self.col.find_one_and_update(
            {"id": integration_id},
            update_doc,
            return_document=ReturnDocument.AFTER,
        )
        return MCPIntegration.model_validate(doc) if doc else None

    async def search(
        self,
        *,
        q: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[MCPIntegration], int]:
        filt: Dict[str, Any] = {"type": "mcp"}
        if tag:
            filt["tags"] = tag
        if q:
            filt["$or"] = [
                {"id": {"$regex": q, "$options": "i"}},
                {"name": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
                {"endpoint": {"$regex": q, "$options": "i"}},
            ]

        total = await self.col.count_documents(filt)
        cursor = (
            self.col.find(filt)
            .sort("name", 1)
            .skip(max(offset, 0))
            .limit(max(min(limit, 200), 1))
        )
        items = [MCPIntegration.model_validate(d) async for d in cursor]
        return items, total

    async def list_all_ids(self) -> List[str]:
        cursor = self.col.find({}, {"id": 1, "_id": 0}).sort("id", 1)
        return [d["id"] async for d in cursor]
