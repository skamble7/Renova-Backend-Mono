from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.dal.capability_dal import CapabilityDAL
from app.events import get_bus
from app.models import GlobalCapability, GlobalCapabilityCreate, GlobalCapabilityUpdate


class CapabilityService:
    def __init__(self) -> None:
        self.dal = CapabilityDAL()

    # ─────────────────────────────────────────────────────────────
    # CRUD
    # ─────────────────────────────────────────────────────────────
    async def create(self, payload: GlobalCapabilityCreate, *, actor: Optional[str] = None) -> GlobalCapability:
        cap = await self.dal.create(payload)
        await get_bus().publish(
            service="capability",
            event="created",
            payload={"id": cap.id, "name": cap.name, "produces_kinds": cap.produces_kinds, "by": actor},
        )
        return cap

    async def get(self, capability_id: str) -> Optional[GlobalCapability]:
        return await self.dal.get(capability_id)

    async def update(self, capability_id: str, patch: GlobalCapabilityUpdate, *, actor: Optional[str] = None) -> Optional[GlobalCapability]:
        cap = await self.dal.update(capability_id, patch)
        if cap:
            await get_bus().publish(
                service="capability",
                event="updated",
                payload={"id": cap.id, "name": cap.name, "produces_kinds": cap.produces_kinds, "by": actor},
            )
        return cap

    async def delete(self, capability_id: str, *, actor: Optional[str] = None) -> bool:
        ok = await self.dal.delete(capability_id)
        if ok:
            await get_bus().publish(
                service="capability",
                event="deleted",
                payload={"id": capability_id, "by": actor},
            )
        return ok

    async def search(
        self,
        *,
        tag: Optional[str] = None,
        produces_kind: Optional[str] = None,
        q: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[GlobalCapability], int]:
        return await self.dal.search(tag=tag, produces_kind=produces_kind, q=q, limit=limit, offset=offset)

    async def list_all_ids(self) -> List[str]:
        return await self.dal.list_all_ids()
