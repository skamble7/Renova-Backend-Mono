# services/learning-service/app/graphs/nodes/gate_produced_node.py
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Set

from app.infra.rabbit import publish_step_event_v1
from app.models.events import LearningStepCompleted, LearningStepFailed, StepInfo

log = logging.getLogger("app.graphs.nodes.gate_produced")


async def gate_produced_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure the current step produced the declared kinds, but allow soft-fail
    so we don't lose already-generated artifacts.

    Soft-fail is enabled if either:
      - state.options.allow_partial_step_failures == True
      - step.params.allow_missing_kinds == True
    In soft-fail mode we log a warning and continue.

    Also publishes step.completed or step.failed as appropriate.
    """
    idx = int(state.get("_step_index", 0))
    steps = (state.get("plan") or {}).get("steps") or []
    step: Dict[str, Any] = steps[idx] if 0 <= idx < len(steps) else {}

    step_id = str(step.get("id") or step.get("step_id") or f"step{idx+1}")
    rt_map = state.setdefault("_step_runtime", {})
    rt = rt_map.setdefault(step_id, {})
    started_at = rt.get("started_at") or datetime.utcnow()

    required: Set[str] = set(step.get("produces_kinds") or [])
    if not required:
        # Nothing to gate -> mark completed
        ended_at = datetime.utcnow()
        payload = LearningStepCompleted(
            run_id=state["run_id"],
            workspace_id=state["workspace_id"],
            playbook_id=state["playbook_id"],
            step=StepInfo(id=step_id, capability_id=step.get("capability_id"), name=step.get("name")),
            params=(step.get("params") or {}),
            produces_kinds=list(step.get("produces_kinds") or []),
            started_at=started_at,
            ended_at=ended_at,
            duration_s=(ended_at - started_at).total_seconds(),
        ).model_dump(mode="json")
        headers = {}
        if state.get("correlation_id"):
            headers["x-correlation-id"] = state["correlation_id"]
        await publish_step_event_v1(status="completed", payload=payload, headers=headers)
        rt["status"] = "completed"
        return state

    # last_validated contains envelopes produced by THIS step
    produced_now: Set[str] = set()
    for env in (state.get("last_validated") or []):
        k = (env.get("kind_id") or env.get("kind") or "").strip()
        if k:
            produced_now.add(k)

    missing = sorted(list(required - produced_now))
    if not missing:
        # success path
        ended_at = datetime.utcnow()
        payload = LearningStepCompleted(
            run_id=state["run_id"],
            workspace_id=state["workspace_id"],
            playbook_id=state["playbook_id"],
            step=StepInfo(id=step_id, capability_id=step.get("capability_id"), name=step.get("name")),
            params=(step.get("params") or {}),
            produces_kinds=list(step.get("produces_kinds") or []),
            started_at=started_at,
            ended_at=ended_at,
            duration_s=(ended_at - started_at).total_seconds(),
        ).model_dump(mode="json")
        headers = {}
        if state.get("correlation_id"):
            headers["x-correlation-id"] = state["correlation_id"]
        await publish_step_event_v1(status="completed", payload=payload, headers=headers)
        rt["status"] = "completed"
        return state

    # Soft-fail toggles
    opts = state.get("options") or {}
    step_params = step.get("params") or {}
    allow_partial = bool(
        opts.get("allow_partial_step_failures") or step_params.get("allow_missing_kinds")
    )

    if allow_partial:
        step_name = step.get("id") or step.get("name") or f"step{idx+1}"
        msg = (
            f"gate_produced_node: step '{step_name}' missing kinds {missing}; "
            f"continuing due to allow_partial_step_failures/allow_missing_kinds"
        )
        log.warning(msg)
        (state.setdefault("warnings", [])).append(msg)
        # Even in soft fail we consider the step "completed" for lifecycle purposes
        ended_at = datetime.utcnow()
        payload = LearningStepCompleted(
            run_id=state["run_id"],
            workspace_id=state["workspace_id"],
            playbook_id=state["playbook_id"],
            step=StepInfo(id=step_id, capability_id=step.get("capability_id"), name=step.get("name")),
            params=(step.get("params") or {}),
            produces_kinds=list(step.get("produces_kinds") or []),
            started_at=started_at,
            ended_at=ended_at,
            duration_s=(ended_at - started_at).total_seconds(),
        ).model_dump(mode="json")
        headers = {}
        if state.get("correlation_id"):
            headers["x-correlation-id"] = state["correlation_id"]
        await publish_step_event_v1(status="completed", payload=payload, headers=headers)
        rt["status"] = "completed"
        return state

    # Strict mode -> hard fail (publish then raise)
    ended_at = datetime.utcnow()
    payload = LearningStepFailed(
        run_id=state["run_id"],
        workspace_id=state["workspace_id"],
        playbook_id=state["playbook_id"],
        step=StepInfo(id=step_id, capability_id=step.get("capability_id"), name=step.get("name")),
        params=(step.get("params") or {}),
        produces_kinds=list(step.get("produces_kinds") or []),
        started_at=started_at,
        ended_at=ended_at,
        duration_s=(ended_at - started_at).total_seconds(),
        error=f"Missing required kinds: {missing}",
    ).model_dump(mode="json")
    headers = {}
    if state.get("correlation_id"):
        headers["x-correlation-id"] = state["correlation_id"]
    await publish_step_event_v1(status="failed", payload=payload, headers=headers)
    rt["status"] = "failed"

    raise RuntimeError(
        f"Step '{step.get('id') or step.get('name')}' did not produce required kinds: {missing}"
    )
