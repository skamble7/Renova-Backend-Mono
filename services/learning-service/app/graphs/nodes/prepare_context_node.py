# services/learning-service/app/graphs/nodes/prepare_context_node.py
from __future__ import annotations

from typing import Any, Dict, List


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
        # Prefer unique by identity if present
        # Keep simple; dedup later in validation if needed
        ctx[dep] = vals
    return ctx


async def prepare_context_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Builds a step-local context bundle using depends_on.
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
    return state
