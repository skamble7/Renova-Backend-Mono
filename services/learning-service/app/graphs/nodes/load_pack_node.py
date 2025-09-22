from __future__ import annotations

from typing import Any, Dict, List

from app.clients.capability_service import CapabilityServiceClient
from app.agents.registry import build_step_plan


async def load_pack_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Loads the resolved pack, extracts the requested playbook, and builds a normalized execution plan.
    Outputs into state['plan'] = { 'steps': [StepPlan dicts], 'playbook': {...} }
    """
    pack_id: str = state["pack_id"]
    playbook_id: str = state["playbook_id"]
    correlation_id: str | None = state.get("correlation_id")

    async with CapabilityServiceClient() as caps:
        resolved = await caps.get_resolved_pack(pack_id, correlation_id=correlation_id)

    # Find the playbook and its steps
    playbooks: List[Dict[str, Any]] = list(resolved.get("playbooks") or [])
    playbook = next((p for p in playbooks if str(p.get("id")) == playbook_id), None)
    if not playbook:
        raise ValueError(f"playbook not found in pack: {playbook_id}")

    # Cap snapshots are expected either on the pack root or resolved per step.
    # Build a map for quick lookup:
    capsnaps: Dict[str, Dict[str, Any]] = {}
    for c in resolved.get("capabilities") or []:
        cid = c.get("id") or c.get("capability_id")
        if cid:
            capsnaps[str(cid)] = c

    steps_plan = []
    for s in playbook.get("steps", []):
        cid = str(s.get("capability_id"))
        cap_snap = capsnaps.get(cid, {})
        steps_plan.append(build_step_plan(s, cap_snap))

    state["plan"] = {"playbook": playbook, "steps": [sp.__dict__ for sp in steps_plan]}
    return state
