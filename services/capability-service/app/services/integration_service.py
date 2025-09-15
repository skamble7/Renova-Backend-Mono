from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.dal.integration_dal import IntegrationDAL
from app.events import get_bus
from app.models import MCPIntegration


def _endpoint_compat(i: MCPIntegration) -> str:
    """
    Back-compat 'endpoint' string for legacy consumers:
    - http: return base_url
    - stdio: return "stdio:<command> [cwd=<cwd>]"
    """
    try:
        t = i.transport
        kind = getattr(t, "kind", None)
        if kind == "http":
            base_url = getattr(t, "base_url", None)
            return str(base_url) if base_url else "http:<unknown>"
        if kind == "stdio":
            cmd = getattr(t, "command", "<cmd>")
            cwd = getattr(t, "cwd", None)
            return f"stdio:{cmd}" + (f" [cwd={cwd}]" if cwd else "")
    except Exception:
        pass
    return "<unknown>"

def _transport_summary(i: MCPIntegration) -> Dict[str, Any]:
    """
    Compact transport info for event payloads.
    """
    try:
        t = i.transport
        kind = getattr(t, "kind", None)
        if kind == "http":
            return {
                "kind": "http",
                "base_url": getattr(t, "base_url", None),
                "timeout_sec": getattr(t, "timeout_sec", None),
                "retry_max_attempts": getattr(t, "retry_max_attempts", None),
            }
        if kind == "stdio":
            return {
                "kind": "stdio",
                "command": getattr(t, "command", None),
                "cwd": getattr(t, "cwd", None),
                "restart_on_exit": getattr(t, "restart_on_exit", None),
                "readiness_regex": getattr(t, "readiness_regex", None),
            }
    except Exception:
        pass
    return {"kind": "unknown"}
    

class IntegrationService:
    def __init__(self) -> None:
        self.dal = IntegrationDAL()

    async def create(self, integ: MCPIntegration, *, actor: Optional[str] = None) -> MCPIntegration:
        created = await self.dal.create(integ)
        await get_bus().publish(
            service="capability",
            event="integration.created",
            payload={
                "id": created.id,
                "name": created.name,
                # Back-compat field; derived from transport so old consumers don't break
                "endpoint": _endpoint_compat(created),
                # New structured transport summary
                "transport": _transport_summary(created),
                "by": actor,
            },
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
                payload={
                    "id": updated.id,
                    "name": updated.name,
                    "endpoint": _endpoint_compat(updated),   # back-compat
                    "transport": _transport_summary(updated),
                    "by": actor,
                },
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

    async def search(
        self,
        *,
        q: Optional[str] = None,
        tag: Optional[str] = None,
        kind: Optional[str] = None,   # NEW: "http" | "stdio"
        limit: int = 50,
        offset: int = 0,
    ):
        return await self.dal.search(q=q, tag=tag, kind=kind, limit=limit, offset=offset)

    async def list_all_ids(self) -> List[str]:
        return await self.dal.list_all_ids()
