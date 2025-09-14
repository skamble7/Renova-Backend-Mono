from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.dal.capability_dal import CapabilityDAL
from app.dal.pack_dal import PackDAL
from app.events import get_bus
from app.models import (
    CapabilityPack,
    CapabilityPackCreate,
    CapabilityPackUpdate,
    CapabilitySnapshot,
    ResolvedPackView,
    ResolvedPlaybook,
    ResolvedPlaybookStep,
)
from app.services.validation import ensure_pack_capabilities_exist, snapshot_from_capability_doc


class PackService:
    def __init__(self) -> None:
        self.packs = PackDAL()
        self.caps = CapabilityDAL()

    # ─────────────────────────────────────────────────────────────
    # CRUD
    # ─────────────────────────────────────────────────────────────
    async def create(self, payload: CapabilityPackCreate, *, actor: Optional[str] = None) -> CapabilityPack:
        pack = await self.packs.create(payload, created_by=actor)
        await get_bus().publish(
            service="capability",
            event="pack.created",
            payload={"pack_id": pack.id, "key": pack.key, "version": pack.version, "by": actor},
        )
        return pack

    async def get(self, pack_id: str) -> Optional[CapabilityPack]:
        return await self.packs.get(pack_id)

    async def get_by_key_version(self, key: str, version: str) -> Optional[CapabilityPack]:
        return await self.packs.get_by_key_version(key, version)

    async def update(self, pack_id: str, patch: CapabilityPackUpdate, *, actor: Optional[str] = None) -> Optional[CapabilityPack]:
        pack = await self.packs.update(pack_id, patch, updated_by=actor)
        if pack:
            await get_bus().publish(
                service="capability",
                event="pack.updated",
                payload={"pack_id": pack.id, "key": pack.key, "version": pack.version, "by": actor},
            )
        return pack

    async def delete(self, pack_id: str, *, actor: Optional[str] = None) -> bool:
        ok = await self.packs.delete(pack_id)
        if ok:
            await get_bus().publish(
                service="capability",
                event="pack.deleted",
                payload={"pack_id": pack_id, "by": actor},
            )
        return ok

    # ─────────────────────────────────────────────────────────────
    # Snapshots & publish
    # ─────────────────────────────────────────────────────────────
    async def refresh_snapshots(self, pack_id: str) -> Optional[CapabilityPack]:
        """
        Build capability snapshots from the current GlobalCapability docs
        referenced by the pack's capability_ids, then persist.
        """
        pack = await self.packs.get(pack_id)
        if not pack:
            return None

        all_ids = await self.caps.list_all_ids()
        ensure_pack_capabilities_exist(pack, all_ids)

        # Load full docs and convert to snapshots
        snapshots: List[Dict[str, Any]] = []
        for cap_id in pack.capability_ids:
            cap_doc = await self.caps.col.find_one({"id": cap_id})
            if not cap_doc:
                continue
            snap = snapshot_from_capability_doc(cap_doc)
            snapshots.append(snap.model_dump())

        return await self.packs.set_capability_snapshots(pack_id, snapshots)

    async def publish(self, pack_id: str, *, actor: Optional[str] = None) -> Optional[CapabilityPack]:
        """
        Refresh snapshots, then set status=published.
        """
        refreshed = await self.refresh_snapshots(pack_id)
        if not refreshed:
            return None
        published = await self.packs.publish(pack_id)
        if published:
            await get_bus().publish(
                service="capability",
                event="pack.published",
                payload={"pack_id": published.id, "key": published.key, "version": published.version, "by": actor},
            )
        return published

    # ─────────────────────────────────────────────────────────────
    # Search / listing
    # ─────────────────────────────────────────────────────────────
    async def search(self, *, key: Optional[str] = None, version: Optional[str] = None, status: Optional[str] = None,
                     q: Optional[str] = None, limit: int = 50, offset: int = 0):
        return await self.packs.search(key=key, version=version, status=status, q=q, limit=limit, offset=offset)

    async def list_versions(self, key: str) -> List[str]:
        return await self.packs.list_versions(key)

    # ─────────────────────────────────────────────────────────────
    # Resolved view (projection; no CAM dependency math here)
    # ─────────────────────────────────────────────────────────────
    async def resolved_view(self, pack_id: str) -> Optional[ResolvedPackView]:
        pack = await self.packs.get(pack_id)
        if not pack:
            return None

        # Map cap_id -> snapshot (if present)
        id_to_snap: Dict[str, CapabilitySnapshot] = {snap.id: snap for snap in pack.capabilities}

        resolved_playbooks: List[ResolvedPlaybook] = []
        for pb in pack.playbooks:
            steps: List[ResolvedPlaybookStep] = []
            for step in pb.steps:
                snap = id_to_snap.get(step.capability_id)
                produces = snap.produces_kinds if snap else []
                mode = "mcp" if (snap and snap.integration is not None) else "llm"
                tool_calls = snap.integration.tool_calls if (snap and snap.integration is not None) else None
                steps.append(
                    ResolvedPlaybookStep(
                        id=step.id,
                        name=step.name,
                        capability_id=step.capability_id,
                        params=step.params or {},
                        execution_mode=mode,               # "mcp" | "llm"
                        produces_kinds=produces,
                        required_kinds=[],                 # learning-service will compute from CAM
                        tool_calls=tool_calls,
                    )
                )
            resolved_playbooks.append(
                ResolvedPlaybook(
                    id=pb.id,
                    name=pb.name,
                    description=pb.description,
                    steps=steps,
                )
            )

        return ResolvedPackView(
            pack_id=pack.id,
            key=pack.key,
            version=pack.version,
            title=pack.title,
            description=pack.description,
            playbooks=resolved_playbooks,
        )
