from __future__ import annotations

from typing import Any, Dict

from langgraph.graph import StateGraph, END

from app.graphs.nodes.ingest_node import ingest_node
from app.graphs.nodes.load_pack_node import load_pack_node
from app.graphs.nodes.preflight_node import preflight_node
from app.graphs.nodes.prepare_context_node import prepare_context_node
from app.graphs.nodes.exec_mcp_node import exec_mcp_node
from app.graphs.nodes.exec_llm_node import exec_llm_node
from app.graphs.nodes.validate_node import validate_node
from app.graphs.nodes.diff_node import diff_node
from app.graphs.nodes.audit_node import audit_node
from app.graphs.nodes.finalize_node import finalize_node

from typing import Optional
from pydantic import UUID4

from app.clients.capability_service import CapabilityServiceClient
from app.agents.registry import build_step_plan
from app.db.runs import mark_run_status, set_run_summary_times
from app.models.run import LearningRun


def build_graph(initial_state: Dict[str, Any]) -> Any:
    """
    Build a LangGraph with nodes wired sequentially based on the plan.
    This compiles a graph instance per run (since steps vary per playbook).
    """
    # 1) static prologue
    graph = StateGraph(dict)

    graph.add_node("ingest", ingest_node)
    graph.add_node("load_pack", load_pack_node)
    graph.add_node("preflight", preflight_node)

    # Entry point
    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "load_pack")
    graph.add_edge("load_pack", "preflight")

    # 2) dynamically add per-step subgraph
    # We temporarily run ingest/load_pack/preflight synchronously to know steps.
    # For simplicity, we assume initial_state already has 'plan' (or we will patch it later).
    # A pragmatic trick: we inspect initial_state['plan']['steps'] if present; else we add one generic slot.
    steps = (initial_state.get("plan") or {}).get("steps") or []

    last = "preflight"
    for i, step in enumerate(steps):
        # Within the state, we keep a moving index so nodes know which step they’re operating on.
        def set_index_wrapper(fn, index: int):
            async def wrapped(s: Dict[str, Any]) -> Dict[str, Any]:
                s["_step_index"] = index
                return await fn(s)
            return wrapped

        ctx_node = f"{step['step_id']}.ctx"
        exec_node = f"{step['step_id']}.exec"
        val_node = f"{step['step_id']}.validate"
        diff_node_name = f"{step['step_id']}.diff"
        audit_node_name = f"{step['step_id']}.audit"

        graph.add_node(ctx_node, set_index_wrapper(prepare_context_node, i))
        if step["mode"] == "mcp":
            graph.add_node(exec_node, set_index_wrapper(exec_mcp_node, i))
        else:
            graph.add_node(exec_node, set_index_wrapper(exec_llm_node, i))
        graph.add_node(val_node, set_index_wrapper(validate_node, i))
        graph.add_node(diff_node_name, set_index_wrapper(diff_node, i))
        graph.add_node(audit_node_name, set_index_wrapper(audit_node, i))

        graph.add_edge(last, ctx_node)
        graph.add_edge(ctx_node, exec_node)
        graph.add_edge(exec_node, val_node)
        graph.add_edge(val_node, diff_node_name)
        graph.add_edge(diff_node_name, audit_node_name)
        last = audit_node_name

    # 3) finalize
    graph.add_node("finalize", finalize_node)
    graph.add_edge(last, "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


async def _prefetch_plan(pack_id: str, playbook_id: str, correlation_id: Optional[str]) -> dict:
    """
    Fetch resolved pack and produce a normalized plan with StepPlan dicts.
    """
    async with CapabilityServiceClient() as caps:
        resolved = await caps.get_resolved_pack(pack_id, correlation_id=correlation_id)

    # Build capability snapshot map
    capsnaps: dict[str, dict] = {}
    for c in resolved.get("capabilities") or []:
        cid = c.get("id") or c.get("capability_id")
        if cid:
            capsnaps[str(cid)] = c

    # Find playbook
    playbook = next((p for p in (resolved.get("playbooks") or []) if str(p.get("id")) == playbook_id), None)
    if not playbook:
        raise ValueError(f"playbook not found in pack: {playbook_id}")

    # Build step plans
    steps_plan = []
    for s in playbook.get("steps", []):
        cid = str(s.get("capability_id"))
        cap_snap = capsnaps.get(cid, {})
        steps_plan.append(build_step_plan(s, cap_snap).__dict__)

    return {"playbook": playbook, "steps": steps_plan}


async def execute_run(run: LearningRun, *, correlation_id: Optional[str]) -> None:
    """
    Build initial state, compile the graph (with plan preloaded), and execute it.
    Ensures run status/timestamps are set on failure as well.
    """
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
        # Prefetch plan so the graph can be compiled with dynamic per-step nodes
        initial_state["plan"] = await _prefetch_plan(run.pack_id, run.playbook_id, correlation_id)
        graph = build_graph(initial_state)
        # Execute the compiled graph
        if hasattr(graph, "ainvoke"):
            await graph.ainvoke(initial_state)
        else:
            # Older langgraph versions
            await graph.invoke(initial_state)  # type: ignore[attr-defined]
    except Exception as e:
        # Mark as failed and finalize timestamps
        await mark_run_status(run.run_id, "failed")
        await set_run_summary_times(run.run_id, completed_at=datetime.utcnow())
        raise


async def execute_run_by_id(run_id: UUID4, *, correlation_id: Optional[str]) -> None:
    """
    Convenience wrapper to load a run and execute it.
    """
    from app.db.runs import get_run  # local import to avoid cycles
    run = await get_run(run_id)
    if not run:
        return
    await execute_run(run, correlation_id=correlation_id)
