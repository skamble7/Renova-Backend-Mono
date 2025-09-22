from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from pydantic import UUID4

from app.clients.artifact_service import ArtifactServiceClient
from app.db.runs import mark_run_status, set_run_summary_times, append_notes_md
from app.agents.report_builder import artifact_counts_md, run_footer_md


async def _flatten_envelopes(produced: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for items in (produced or {}).values():
        flat.extend(items)
    return flat


async def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Persist baseline (if strategy == baseline) to artifact-service.
    Finalize times and mark status, append a footer to notes.
    """
    run_id = state["run_id"]
    workspace_id: UUID4 = state["workspace_id"]
    strategy = state["strategy"]
    produced = state.get("produced", {})

    # Aggregate counts for notes
    total_by_kind = {k: len(v) for k, v in (produced or {}).items()}
    await append_notes_md(run_id, artifact_counts_md(total_by_kind))

    if strategy == "baseline" and produced:
        # Convert envelopes into artifact-service upsert-batch payloads
        items = []
        for env in _flatten_envelopes(produced):
            items.append(
                {
                    "kind": env["kind_id"],
                    "data": env["data"],
                    "schema_version": env.get("schema_version", "1.0.0"),
                    # Optionally include identity if the artifact-service payload supports it
                    "identity": env.get("identity"),
                }
            )
        async with ArtifactServiceClient() as arts:
            await arts.upsert_batch(workspace_id, items)

    await set_run_summary_times(run_id, completed_at=datetime.utcnow())
    await mark_run_status(run_id, "completed")
    await append_notes_md(run_id, run_footer_md(datetime.utcnow()))
    return state
