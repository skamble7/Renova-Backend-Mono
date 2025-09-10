from __future__ import annotations
import hashlib, uuid, datetime as dt
from typing import Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..dal import capability_dal as caps_dal
from ..dal import integrations_dal as integ_dal
from ..models.capability_pack import CapabilityPack, Playbook
from ..models.integrations import ExecutionPlan
from .schema_utils import validate_against_schema

async def resolve_plan(db: AsyncIOMotorDatabase, pack_key: str, pack_version: str, pb_id: str, workspace_id: str, overrides: Dict[str, Any]) -> ExecutionPlan | None:
    pack = await caps_dal.get_pack(db, pack_key, pack_version)
    if not pack:
        return None

    # pick playbook
    pb: Playbook | None = next((p for p in pack.playbooks if p.id == pb_id), None)
    if not pb:
        return None

    # validate steps
    capset = set(pack.capability_ids or [])
    resolved_tools: List[Dict[str, Any]] = []

    for st in pb.steps:
        if getattr(st, "type", "capability") == "capability":
            if st.capability_id not in capset:
                raise ValueError(f"Unknown capability_id '{st.capability_id}'")
        else:
            tool_key = getattr(st, "tool_key")
            t = await integ_dal.get_tool(db, tool_key)
            if not t:
                raise ValueError(f"Unknown tool_key '{tool_key}'")
            c = await integ_dal.get_connector(db, t.connector_key)
            if not c:
                raise ValueError(f"Unknown connector_key '{t.connector_key}'")
            # Validate schemas if present
            if t.input_schema:
                validate_against_schema(st.params or {}, t.input_schema)
            resolved_tools.append({
                "step_id": st.id,
                "tool_key": t.key,
                "connector_key": t.connector_key,
                "operation": t.operation,
            })

    # normalize edges (linear fallback)
    edges = pb.edges or [{"from": pb.steps[i].id, "to": pb.steps[i+1].id} for i in range(len(pb.steps)-1)]

    # artifacts contract
    artifacts_contract = list({*sum([getattr(s, "emits", []) for s in pb.steps], []), *pb.produces})

    # plan_id: stable-ish hash (pack+pb+workspace+updated_at)
    basis = f"{pack.key}:{pack.version}:{pb.id}:{workspace_id}:{pack.updated_at.isoformat()}"
    plan_id = "pln_" + hashlib.sha1(basis.encode()).hexdigest()[:16]

    return ExecutionPlan(
        plan_id=plan_id,
        pack={"key": pack.key, "version": pack.version},
        playbook={"id": pb.id, "steps": [s.model_dump() for s in pb.steps], "edges": edges},
        resolved_tools=resolved_tools,
        policies=pack.default_policies or {},
        artifacts_contract=artifacts_contract,
    )
