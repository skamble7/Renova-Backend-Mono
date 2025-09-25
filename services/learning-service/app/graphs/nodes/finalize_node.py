# services/learning-service/app/graphs/nodes/finalize_node.py
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List

from pydantic import UUID4

from app.clients.artifact_service import ArtifactServiceClient
from app.db.runs import mark_run_status, set_run_summary_times, append_notes_md
from app.agents.report_builder import artifact_counts_md, run_footer_md
from app.infra.rabbit import publish_event_v1
from app.models.events import LearningRunCompleted, LearningRunCompletedInterim


def _flatten_envelopes(produced: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """
    Flatten {kind_id: [envelopes...]} into a single list of envelopes.
    Each envelope is expected to look like:
      {"kind_id": str, "data": dict, "schema_version": "1.0.0", ...}
    """
    flat: List[Dict[str, Any]] = []
    for items in (produced or {}).values():
        if not items:
            continue
        flat.extend(items)
    return flat


def _derive_name(kind: str, data: Dict[str, Any]) -> str:
    """
    Produce a stable, human-ish name when the envelope doesn't provide one.
    """
    kind = kind or ""
    data = data or {}

    if kind == "cam.asset.repo_snapshot":
        repo = (data.get("repo") or "").rstrip("/")
        base = os.path.basename(repo) or repo or "repo"
        commit = (data.get("commit") or "")[:12]
        return f"{base}@{commit}" if commit else base

    if kind == "cam.asset.source_index":
        root = (data.get("root") or "").rstrip("/")
        base = os.path.basename(root) or root or "source"
        return f"source-index:{base}"

    if kind == "cam.cobol.program":
        return data.get("program_id") or (data.get("source") or {}).get("relpath") or "program"

    if kind == "cam.cobol.copybook":
        return data.get("name") or (data.get("source") or {}).get("relpath") or "copybook"

    # Default fallback
    return (data.get("name")
            or (data.get("source") or {}).get("relpath")
            or kind
            or "artifact")


def _envelope_to_item(env: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map our internal envelope to artifact-service upsert-batch item shape.
    Required by artifact-service: name, kind, data, schema_version
    Optional: identity, tags
    """
    kind = env.get("kind_id") or env.get("kind")
    data = env.get("data") or env.get("body") or {}

    if not kind:
        # Skip malformed envelopes defensively
        return {}

    name = env.get("name") or _derive_name(kind, data)

    item: Dict[str, Any] = {
        "name": name,
        "kind": kind,
        "data": data,
        "schema_version": env.get("schema_version", "1.0.0"),
    }

    identity = env.get("identity")
    if identity:
        item["identity"] = identity

    tags = env.get("tags", [])
    # Ensure tags is a list
    if not isinstance(tags, list):
        tags = [str(tags)]
    item["tags"] = tags

    return item


async def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Persist baseline (if strategy == baseline) to artifact-service.
    Finalize times and mark status, append a footer to notes.
    Also emits both the interim 'completed' (B) and final 'completed' (A) events.
    """
    run_id = state["run_id"]
    workspace_id: UUID4 = state["workspace_id"]
    strategy = state.get("strategy")
    produced: Dict[str, List[Dict[str, Any]]] = state.get("produced", {}) or {}

    # Aggregate counts for notes
    total_by_kind = {k: len(v or []) for k, v in produced.items()}
    await append_notes_md(run_id, artifact_counts_md(total_by_kind))

    # Persist baseline if applicable
    if strategy == "baseline" and produced:
        # Convert envelopes → artifact-service upsert-batch items
        items: List[Dict[str, Any]] = []
        for env in _flatten_envelopes(produced):
            if not env:
                continue
            item = _envelope_to_item(env)
            if item:  # skip malformed
                items.append(item)

        if items:
            async with ArtifactServiceClient() as arts:
                await arts.upsert_batch(workspace_id, items)

    # Emit interim 'completed' (B) with deltas.counts
    try:
        counts = (((state.get("deltas") or {}).get("counts")) or {})
        interim = LearningRunCompletedInterim(
            run_id=run_id,
            workspace_id=workspace_id,
            playbook_id=state["playbook_id"],
            artifact_ids=[],  # learning-service does not track persisted IDs here
            artifact_failures=list(state.get("errors") or []),
            validations=list(state.get("validations") or []),
            deltas={"counts": {k: int(counts.get(k, 0)) for k in ("new", "updated", "unchanged", "retired", "added", "changed", "removed")}},
        )
        headers = {}
        if state.get("correlation_id"):
            headers["x-correlation-id"] = state["correlation_id"]
        await publish_event_v1(event="completed", payload=interim.model_dump(mode="json"), headers=headers)
    except Exception:
        # Non-fatal if interim publish fails
        pass

    # Always finalize times/status, even if no artifacts
    now = datetime.utcnow()
    await set_run_summary_times(run_id, completed_at=now)
    await mark_run_status(run_id, "completed")
    await append_notes_md(run_id, run_footer_md(now))

    # Emit final 'completed' (A) with run duration & timestamps
    started_at = state.get("started_at") or now
    final_evt = LearningRunCompleted(
        run_id=run_id,
        workspace_id=workspace_id,
        playbook_id=state["playbook_id"],
        artifact_ids=[],                       # not tracked here
        validations=list(state.get("validations") or []),
        started_at=started_at,
        completed_at=now,
        duration_s=(now - started_at).total_seconds(),
        title=state.get("title"),
        description=state.get("description"),
    )
    headers = {}
    if state.get("correlation_id"):
        headers["x-correlation-id"] = state["correlation_id"]
    await publish_event_v1(event="completed", payload=final_evt.model_dump(mode="json"), headers=headers)

    return state
