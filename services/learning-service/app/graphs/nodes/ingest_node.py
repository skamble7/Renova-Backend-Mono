# services/learning-service/app/graphs/nodes/ingest_node.py
from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

from pydantic import UUID4

from app.db.runs import mark_run_status, set_run_summary_times, append_notes_md
from app.agents.report_builder import run_header_md


async def ingest_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize run in DB and seed notes.
    Expects: run_id, workspace_id, pack_id, playbook_id, strategy in state.
    """
    run_id: UUID4 = state["run_id"]
    await mark_run_status(run_id, "running")
    await set_run_summary_times(run_id, started_at=datetime.utcnow())

    header = run_header_md(
        {
            "run_id": str(run_id),
            "workspace_id": str(state["workspace_id"]),
            "pack_id": state["pack_id"],
            "playbook_id": state["playbook_id"],
            "strategy": state["strategy"],
            "started_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
    )
    await append_notes_md(run_id, header)

    state.setdefault("logs", [])
    state.setdefault("errors", [])
    state.setdefault("produced", {})
    state.setdefault("diffs_by_kind", {})
    state.setdefault("deltas", {"counts": {}})
    return state
