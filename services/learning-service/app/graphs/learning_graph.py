from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from langgraph.graph import StateGraph, END

# Node funcs
from app.graphs.nodes.preflight_node import preflight_node
from app.graphs.nodes.ingest_node import ingest_node
from app.graphs.nodes.prepare_context_node import prepare_context_node
from app.graphs.nodes.exec_mcp_node import exec_mcp_node
from app.graphs.nodes.exec_llm_node import exec_llm_node
from app.graphs.nodes.validate_node import validate_node
from app.graphs.nodes.diff_node import diff_node
from app.graphs.nodes.audit_node import audit_node
from app.graphs.nodes.finalize_node import finalize_node

from app.agents.registry import build_step_plan
from app.clients.capability_service import CapabilityServiceClient
from app.db.runs import mark_run_status, set_run_summary_times
from app.models.run import LearningRun


def _step_key(step: Dict[str, Any]) -> str:
    return str(step.get("id") or step.get("step_id") or "step")


def build_graph(initial_state: Dict[str, Any]):
    graph = StateGraph(dict)

    # Shared nodes
    graph.add_node("preflight", preflight_node)
    graph.add_node("ingest", ingest_node)
    graph.add_node("diff", diff_node)
    graph.add_node("audit", audit_node)
    graph.add_node("finalize", finalize_node)

    steps = (initial_state.get("plan") or {}).get("steps") or []
    n = len(steps)

    graph.set_entry_point("preflight")
    graph.add_edge("preflight", "ingest")

    if n == 0:
        graph.add_edge("ingest", "diff")
        graph.add_edge("diff", "audit")
        graph.add_edge("audit", "finalize")
        graph.add_edge("finalize", END)
        return graph.compile()

    def make_set_index_node(i: int):
        async def _setter(state: Dict[str, Any]) -> Dict[str, Any]:
            state["_step_index"] = i
            return state
        return _setter

    prev_tail = "ingest"
    for i, step in enumerate(steps):
        skey = _step_key(step)
        set_idx_name = f"{skey}.set"
        ctx_name = f"{skey}.ctx"
        exec_llm_name = f"{skey}.exec.llm"
        exec_mcp_name = f"{skey}.exec.mcp"
        validate_name = f"{skey}.validate"

        graph.add_node(set_idx_name, make_set_index_node(i))
        graph.add_node(ctx_name, prepare_context_node)
        graph.add_node(exec_llm_name, exec_llm_node)
        graph.add_node(exec_mcp_name, exec_mcp_node)
        graph.add_node(validate_name, validate_node)

        graph.add_edge(prev_tail, set_idx_name)
        graph.add_edge(set_idx_name, ctx_name)

        def mode_selector(state: Dict[str, Any]) -> str:
            idx = state.get("_step_index", 0)
            st = (state.get("plan") or {}).get("steps", [])
            if 0 <= idx < len(st):
                mode = (st[idx].get("execution_mode") or "llm").lower()
                return "mcp" if mode == "mcp" else "llm"
            return "llm"

        graph.add_conditional_edges(
            ctx_name,
            mode_selector,
            {"mcp": exec_mcp_name, "llm": exec_llm_name},
        )

        graph.add_edge(exec_mcp_name, validate_name)
        graph.add_edge(exec_llm_name, validate_name)

        prev_tail = validate_name

    graph.add_edge(prev_tail, "diff")
    graph.add_edge("diff", "audit")
    graph.add_edge("audit", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


# ───────────────────────────────────────────────────────────────────────────────
# Execution helpers
# ───────────────────────────────────────────────────────────────────────────────

async def _prefetch_plan(pack_id: str, playbook_id: str, correlation_id: Optional[str]) -> dict:
    """
    Fetch resolved pack and produce a normalized plan with StepPlan dicts.
    Falls back to fetching individual capabilities if the resolved view omits `capabilities[]`.
    """
    async with CapabilityServiceClient() as caps:
        resolved = await caps.get_resolved_pack(pack_id, correlation_id=correlation_id)

        # Capability snapshots map (if present)
        capsnaps: dict[str, dict] = {}
        for c in resolved.get("capabilities") or []:
            cid = c.get("id") or c.get("capability_id")
            if cid:
                capsnaps[str(cid)] = c

        # Find playbook
        playbook = next((p for p in (resolved.get("playbooks") or []) if str(p.get("id")) == playbook_id), None)
        if not playbook:
            raise ValueError(f"playbook not found in pack: {playbook_id}")

        # Build step plans (fallback to fetching capability when not in resolved pack)
        steps_plan = []
        for s in playbook.get("steps", []):
            cid = str(s.get("capability_id"))
            cap_snap = capsnaps.get(cid)
            if cap_snap is None:
                try:
                    cap_snap = await caps.get_capability(cid, correlation_id=correlation_id)
                except Exception:
                    cap_snap = {}
            steps_plan.append(build_step_plan(s, cap_snap).model_dump())

    return {"playbook": playbook, "steps": steps_plan}


async def execute_run(run: LearningRun, *, correlation_id: Optional[str]) -> None:
    initial_state = {
        "run_id": run.run_id,
        "workspace_id": run.workspace_id,
        "pack_id": run.pack_id,
        "playbook_id": run.playbook_id,
        "strategy": run.strategy,
        "inputs": run.inputs.model_dump(),
        "options": run.options.model_dump() if hasattr(run.options, "model_dump") else dict(run.options or {}),
        "correlation_id": correlation_id,
        "input_fingerprint": run.input_fingerprint,
    }

    try:
        initial_state["plan"] = await _prefetch_plan(run.pack_id, run.playbook_id, correlation_id)
        graph = build_graph(initial_state)

        try:
            await mark_run_status(run.run_id, "running")
            await set_run_summary_times(run.run_id, started_at=datetime.utcnow())
        except Exception:
            pass

        if hasattr(graph, "ainvoke"):
            await graph.ainvoke(initial_state)
        else:
            await graph.invoke(initial_state)  # type: ignore[attr-defined]

    except Exception:
        try:
            await mark_run_status(run.run_id, "failed")
            await set_run_summary_times(run.run_id, completed_at=datetime.utcnow())
        except Exception:
            pass
        raise


async def execute_run_by_id(run_id, *, correlation_id: Optional[str]) -> None:
    from app.db.runs import get_run
    run = await get_run(run_id)
    if not run:
        return
    await execute_run(run, correlation_id=correlation_id)
