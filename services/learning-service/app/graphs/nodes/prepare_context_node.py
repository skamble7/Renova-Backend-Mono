# services/learning-service/app/graphs/nodes/prepare_context_node.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.infra.rabbit import publish_step_event_v1
from app.models.events import LearningStepStarted, StepInfo


def _collect_context_for_kind(
    kind_id: str,
    *,
    produced: Dict[str, List[Dict[str, Any]]],
    baseline: Dict[str, List[Dict[str, Any]]],
    depends_map: Dict[str, List[str]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    For a target kind, gather context artifacts from 'produced' first, then fallback to 'baseline'.
    Returns a {dep_kind_id: [artifacts]} mapping.
    """
    ctx: Dict[str, List[Dict[str, Any]]] = {}
    for dep in depends_map.get(kind_id, []):
        vals = (produced.get(dep) or []) + ([] if dep not in baseline else baseline.get(dep, []))
        ctx[dep] = vals
    return ctx


async def prepare_context_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Builds a step-local context bundle using depends_on.
    Also emits 'step' + 'step.started' once per step (idempotent).
    Places the bundle under state['context'] for the current step.
    """
    idx = state.get("_step_index", 0)
    step = state["plan"]["steps"][idx]

    produced = state.get("produced", {})
    baseline = state.get("baseline", {})
    depends_map = state.get("depends", {})

    # Union context for *all* kinds produced by this step
    bundle: Dict[str, List[Dict[str, Any]]] = {}
    for k in step["produces_kinds"]:
        sub = _collect_context_for_kind(k, produced=produced, baseline=baseline, depends_map=depends_map)
        for dk, items in sub.items():
            bundle.setdefault(dk, [])
            bundle[dk].extend(items)
    state["context"] = bundle

    # --- Publish step.started only once per step
    step_id = str(step.get("id") or step.get("step_id") or f"step{idx+1}")
    rt = state.setdefault("_step_runtime", {})
    if step_id not in rt:
        started_at = datetime.utcnow()
        rt[step_id] = {"started_at": started_at, "status": "started"}

        payload = LearningStepStarted(
            run_id=state["run_id"],
            workspace_id=state["workspace_id"],
            playbook_id=state["playbook_id"],
            step=StepInfo(id=step_id, capability_id=step.get("capability_id"), name=step.get("name")),
            params=(step.get("params") or {}),
            produces_kinds=list(step.get("produces_kinds") or []),
            started_at=started_at,
        ).model_dump(mode="json")

        headers = {}
        if state.get("correlation_id"):
            headers["x-correlation-id"] = state["correlation_id"]
        await publish_step_event_v1(status="started", payload=payload, headers=headers)

    return state
