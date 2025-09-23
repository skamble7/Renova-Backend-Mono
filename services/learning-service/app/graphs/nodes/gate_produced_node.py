# services/learning-service/app/graphs/nodes/gate_produced_node.py
from __future__ import annotations

import logging
from typing import Any, Dict, Set

log = logging.getLogger("app.graphs.nodes.gate_produced")


async def gate_produced_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure the current step produced the declared kinds, but allow soft-fail
    so we don't lose already-generated artifacts.

    Soft-fail is enabled if either:
      - state.options.allow_partial_step_failures == True
      - step.params.allow_missing_kinds == True
    In soft-fail mode we log a warning and continue.
    """
    idx = int(state.get("_step_index", 0))
    steps = (state.get("plan") or {}).get("steps") or []
    step: Dict[str, Any] = steps[idx] if 0 <= idx < len(steps) else {}

    required: Set[str] = set(step.get("produces_kinds") or [])
    if not required:
        return state

    # last_validated contains envelopes produced by THIS step
    produced_now: Set[str] = set()
    for env in (state.get("last_validated") or []):
        k = (env.get("kind_id") or env.get("kind") or "").strip()
        if k:
            produced_now.add(k)

    missing = sorted(list(required - produced_now))
    if not missing:
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
        return state

    # Strict mode -> hard fail (preserves previous artifacts; run will stop here)
    raise RuntimeError(
        f"Step '{step.get('id') or step.get('name')}' did not produce required kinds: {missing}"
    )
