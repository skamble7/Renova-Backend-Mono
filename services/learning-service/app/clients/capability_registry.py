from __future__ import annotations
import httpx
from typing import Optional
from app.config import settings

async def get_pack_and_playbook(*, pack_key: str, pack_version: str, playbook_id: str) -> dict:
    """
    Resolve pack & the specific playbook from capability-service.
    """
    base = settings.CAPABILITY_REGISTRY_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_S) as client:
        p = await client.get(f"{base}/capability/pack/{pack_key}/{pack_version}")
        p.raise_for_status()
        pack = p.json()

        pb = await client.get(f"{base}/capability/pack/{pack_key}/{pack_version}/playbooks")
        pb.raise_for_status()
        playbooks = pb.json() or []
        playbook = next((x for x in playbooks if x.get("id") == playbook_id), None)
        if not playbook:
            raise LookupError(f"playbook {playbook_id} not found in pack {pack_key}/{pack_version}")
        return {"pack": pack, "playbook": playbook}
