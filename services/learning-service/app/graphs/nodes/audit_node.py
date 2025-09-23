# services/learning-service/app/graphs/nodes/audit_node.py
from __future__ import annotations

from typing import Any, Dict, List

from app.db.runs import append_notes_md

# If your DAL exposes this helper (it likely does, given prior runs), use it.
try:
    from app.db.runs import append_audit_entry  # type: ignore
except Exception:  # pragma: no cover
    append_audit_entry = None  # type: ignore


async def audit_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append a concise, step-scoped audit entry to the run document.

    - Uses plan.steps[_step_index] to identify the current step.
    - Normalizes step id field: prefer 'id', fall back to 'step_id'.
    - Captures a light preview of inputs + context keys.
    - Includes any per-step tool call audit in state['_audit_calls'] (if executors set it).
    """
    idx = int(state.get("_step_index", 0))
    steps: List[Dict[str, Any]] = (state.get("plan") or {}).get("steps") or []
    step: Dict[str, Any] = steps[idx] if 0 <= idx < len(steps) else {}

    step_id = str(step.get("id") or step.get("step_id") or f"step{idx+1}")
    cap_id = step.get("capability_id")
    mode = str(step.get("execution_mode") or "llm")

    entry = {
        "step_id": step_id,
        "capability_id": cap_id,
        "mode": mode,  # "mcp" | "llm"
        "inputs_preview": {
            "inputs": state.get("inputs") or {},
            "context_keys": list((state.get("context") or {}).keys()),
        },
        "calls": state.get("_audit_calls") or [],  # optional; executors may populate
    }

    # Try to persist to the 'audit' array; fall back to notes markdown if DAL helper missing.
    try:
        if append_audit_entry:
            await append_audit_entry(state["run_id"], entry)  # type: ignore[misc]
        else:
            md = f"\n\n### Audit: {step_id}\n\n```json\n{entry}\n```\n"
            await append_notes_md(state["run_id"], md)
    except Exception:
        # Never let audit failure break the run; at least drop something into notes.
        md = f"\n\n### Audit (best-effort): {step_id}\n\n```json\n{entry}\n```\n"
        try:
            await append_notes_md(state["run_id"], md)
        except Exception:
            pass

    # Clear any per-step audit calls so the next step starts fresh
    if "_audit_calls" in state:
        state["_audit_calls"] = []

    return state
