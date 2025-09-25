# services/learning-service/app/graphs/nodes/ingest_node.py
from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

from pydantic import UUID4

from app.db.runs import mark_run_status, set_run_summary_times, append_notes_md
from app.agents.report_builder import run_header_md
from app.infra.rabbit import publish_event_v1
from app.models.events import LearningRunStarted


async def ingest_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Initialize run in DB and seed notes.
    Expects: run_id, workspace_id, pack_id, playbook_id, strategy in state.
    Also publishes 'started' event.
    """
    run_id: UUID4 = state["run_id"]
    await mark_run_status(run_id, "running")

    started_at = datetime.utcnow()
    await set_run_summary_times(run_id, started_at=started_at)
    state["started_at"] = started_at  # retain for finalization event

    header = run_header_md(
        {
            "run_id": str(run_id),
            "workspace_id": str(state["workspace_id"]),
            "pack_id": state["pack_id"],
            "playbook_id": state["playbook_id"],
            "strategy": state["strategy"],
            "started_at": started_at.isoformat(timespec="seconds") + "Z",
        }
    )
    await append_notes_md(run_id, header)

    # Publish standardized 'started' event
    model_id = None
    try:
        model_id = (state.get("options") or {}).get("model")
    except Exception:
        pass

    evt = LearningRunStarted(
        run_id=run_id,
        workspace_id=state["workspace_id"],
        pack_id=state.get("pack_id"),
        playbook_id=state["playbook_id"],
        strategy=state["strategy"],
        model_id=model_id,
        received_at=started_at,
        title=state.get("title"),
        description=state.get("description"),
    )
    headers = {}
    if state.get("correlation_id"):
        headers["x-correlation-id"] = state["correlation_id"]
    await publish_event_v1(event="started", payload=evt.model_dump(mode="json"), headers=headers)

    state.setdefault("logs", [])
    state.setdefault("errors", [])
    state.setdefault("produced", {})
    state.setdefault("diffs_by_kind", {})
    state.setdefault("deltas", {"counts": {}})
    return state
