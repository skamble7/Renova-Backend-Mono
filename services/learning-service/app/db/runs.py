from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from motor.motor_asyncio import AsyncIOMotorCollection
from pydantic import UUID4

from app.db.mongo import get_collection
from app.models.run import (
    ArtifactEnvelope,
    LearningRun,
    RunDeltas,
    StepAudit,
)


COLLECTION_NAME = "learning_runs"


# ─────────────────────────────────────────────────────────────
# Helpers: encode/decode between Pydantic models and Mongo docs
# ─────────────────────────────────────────────────────────────

def _encode(obj: Any) -> Any:
    """
    Convert common Python / Pydantic objects into Mongo-safe structures.
    - UUID -> str
    - Pydantic BaseModel -> dict (recursively encoded)
    - Lists/Dicts -> recursively encoded
    Datetimes are kept as datetime for better querying/sorting.
    """
    from pydantic import BaseModel

    if obj is None:
        return None
    if isinstance(obj, BaseModel):
        return _encode(obj.model_dump())
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _encode(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_encode(v) for v in obj]
    # leave datetime and primitives as-is
    return obj


def _col() -> AsyncIOMotorCollection:
    return get_collection(COLLECTION_NAME)


# ─────────────────────────────────────────────────────────────
# DAL operations
# ─────────────────────────────────────────────────────────────

async def create_run(run: LearningRun) -> LearningRun:
    """
    Insert a new run document. Fails if run_id already exists.
    """
    doc = _encode(run)
    await _col().insert_one(doc)
    return run


async def get_run(run_id: UUID4) -> Optional[LearningRun]:
    """
    Fetch a run by run_id.
    """
    doc = await _col().find_one({"run_id": str(run_id)})
    if not doc:
        return None
    # Pydantic will coerce str UUID fields back into UUID types where declared.
    return LearningRun.model_validate(doc)


async def list_runs(
    *,
    workspace_id: Optional[UUID4] = None,
    status: Optional[str] = None,
    pack_id: Optional[str] = None,
    playbook_id: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
) -> List[LearningRun]:
    """
    List runs with common filters. Sorted by created_at desc by default.
    """
    query: Dict[str, Any] = {}
    if workspace_id:
        query["workspace_id"] = str(workspace_id)
    if status:
        query["status"] = status
    if pack_id:
        query["pack_id"] = pack_id
    if playbook_id:
        query["playbook_id"] = playbook_id

    cursor = (
        _col()
        .find(query)
        .sort("created_at", -1)
        .skip(max(skip, 0))
        .limit(max(min(limit, 200), 1))
    )
    results: List[LearningRun] = []
    async for doc in cursor:
        results.append(LearningRun.model_validate(doc))
    return results


async def update_run_fields(run_id: UUID4, patch: Dict[str, Any]) -> int:
    """
    Generic $set update. Returns modified count.
    Always touches updated_at.
    """
    patch = dict(patch or {})
    patch["updated_at"] = datetime.utcnow()

    res = await _col().update_one({"run_id": str(run_id)}, {"$set": _encode(patch)})
    return res.modified_count


async def mark_run_status(run_id: UUID4, status: str) -> int:
    """
    Convenience for updating status field.
    """
    return await update_run_fields(run_id, {"status": status})


async def append_step_audit(run_id: UUID4, step_audit: StepAudit) -> int:
    """
    Append a step audit entry.
    """
    update = {
        "$push": {"audit": _encode(step_audit)},
        "$set": {"updated_at": datetime.utcnow()},
    }
    res = await _col().update_one({"run_id": str(run_id)}, update)
    return res.modified_count


async def append_run_artifacts(run_id: UUID4, artifacts: List[ArtifactEnvelope]) -> int:
    """
    Append produced artifacts to the run document.
    """
    if not artifacts:
        return 0
    update = {
        "$push": {"run_artifacts": {"$each": _encode(artifacts)}},
        "$set": {"updated_at": datetime.utcnow()},
    }
    res = await _col().update_one({"run_id": str(run_id)}, update)
    return res.modified_count


async def set_diffs(run_id: UUID4, diffs_by_kind: Dict[str, Any], deltas: Optional[RunDeltas] = None) -> int:
    """
    Set/replace the diff summary for a run.
    """
    payload: Dict[str, Any] = {
        "diffs_by_kind": _encode(diffs_by_kind),
        "updated_at": datetime.utcnow(),
    }
    if deltas is not None:
        payload["deltas"] = _encode(deltas)
    res = await _col().update_one({"run_id": str(run_id)}, {"$set": payload})
    return res.modified_count


async def append_notes_md(run_id: UUID4, md_chunk: str) -> int:
    """
    Concatenate a Markdown chunk to notes_md.
    Uses $concat with the existing field (creates if missing).
    """
    # Mongo doesn't have $concat on update outside of aggregation pipelines,
    # so we implement a simple two-step append with $set and $ifNull semantics:
    doc = await _col().find_one({"run_id": str(run_id)}, projection={"notes_md": 1})
    current = (doc or {}).get("notes_md") or ""
    new_val = f"{current}{md_chunk}"

    res = await _col().update_one(
        {"run_id": str(run_id)},
        {"$set": {"notes_md": new_val, "updated_at": datetime.utcnow()}},
    )
    return res.modified_count


async def set_run_summary_times(
    run_id: UUID4, *, started_at: Optional[datetime] = None, completed_at: Optional[datetime] = None
) -> int:
    """
    Initialize or finalize RunSummary timestamps and derived duration.
    """
    doc = await _col().find_one({"run_id": str(run_id)}, projection={"run_summary": 1})
    summary = (doc or {}).get("run_summary") or {}

    if started_at is not None:
        summary["started_at"] = started_at
    if completed_at is not None:
        summary["completed_at"] = completed_at
        if "started_at" in summary and isinstance(summary["started_at"], datetime):
            delta = completed_at - summary["started_at"]
            summary["duration_s"] = max(delta.total_seconds(), 0.0)

    res = await _col().update_one(
        {"run_id": str(run_id)},
        {"$set": {"run_summary": summary, "updated_at": datetime.utcnow()}},
        upsert=False,
    )
    return res.modified_count


async def increment_kind_counts(
    run_id: UUID4, counts: Dict[str, int]
) -> int:
    """
    Update a per-run aggregate counter (by kind) for convenience.
    Stores it under run_summary.logs as a lightweight note,
    or could be a dedicated field if preferred later.
    """
    # Keep this conservative: read-modify-write.
    doc = await _col().find_one({"run_id": str(run_id)}, projection={"run_summary": 1})
    summary = (doc or {}).get("run_summary") or {}
    logs: List[str] = summary.get("logs") or []
    stamp = datetime.utcnow().isoformat()
    logs.append(f"[{stamp}] produced_counts: {counts}")
    summary["logs"] = logs

    res = await _col().update_one(
        {"run_id": str(run_id)},
        {"$set": {"run_summary": summary, "updated_at": datetime.utcnow()}},
    )
    return res.modified_count
