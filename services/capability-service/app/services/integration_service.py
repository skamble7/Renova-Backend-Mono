from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.dal.integration_dal import IntegrationDAL
from app.events import get_bus
from app.models import MCPIntegration


class IntegrationService:
    def __init__(self) -> None:
        self.dal = IntegrationDAL()

    async def create(self, integ: MCPIntegration, *, actor: Optional[str] = None) -> MCPIntegration:
        created = await self.dal.create(integ)
        await get_bus().publish(
            service="capability",
            event="integration.created",
            payload={"id": created.id, "name": created.name, "endpoint": created.endpoint, "by": actor},
        )
        return created

    async def get(self, integration_id: str) -> Optional[MCPIntegration]:
        return await self.dal.get(integration_id)

    async def update(self, integration_id: str, patch: Dict[str, Any], *, actor: Optional[str] = None) -> Optional[MCPIntegration]:
        updated = await self.dal.update(integration_id, patch)
        if updated:
            await get_bus().publish(
                service="capability",
                event="integration.updated",
                payload={"id": updated.id, "name": updated.name, "endpoint": updated.endpoint, "by": actor},
            )
        return updated

    async def delete(self, integration_id: str, *, actor: Optional[str] = None) -> bool:
        ok = await self.dal.delete(integration_id)
        if ok:
            await get_bus().publish(
                service="capability",
                event="integration.deleted",
                payload={"id": integration_id, "by": actor},
            )
        return ok

    async def search(self, *, q: Optional[str] = None, tag: Optional[str] = None, limit: int = 50, offset: int = 0):
        return await self.dal.search(q=q, tag=tag, limit=limit, offset=offset)

    async def list_all_ids(self) -> List[str]:
        return await self.dal.list_all_ids()
