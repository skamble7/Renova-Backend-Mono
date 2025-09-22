from __future__ import annotations

from typing import Any, Dict
from datetime import datetime

from app.db.runs import append_notes_md, append_step_audit
from app.agents.report_builder import step_summary_md
from app.models.run import StepAudit, ToolCallAudit


async def audit_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Append step-level audit + notes to the run doc and notes markdown.
    Uses minimal statistics collected in prior nodes.
    """
    run_id = state["run_id"]
    idx = state.get("_step_index", 0)
    step = state["plan"]["steps"][idx]

    stats = state.get("last_stats", {}) or {}
    # Build a simple StepAudit (calls list is left empty here; can be filled by exec nodes later)
    audit = StepAudit(
        step_id=step["step_id"],
        capability_id=step["capability_id"],
        mode=step["mode"],
        inputs_preview={"inputs": state.get("inputs"), "context_keys": list((state.get("context") or {}).keys())},
        calls=[],
    )
    await append_step_audit(run_id, audit)

    md = step_summary_md(step["step_id"], step.get("name", step["step_id"]), stats)
    await append_notes_md(run_id, md)
    return state
