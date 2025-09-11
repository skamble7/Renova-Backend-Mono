# services/learning-service/app/db/learning_runs.py
from datetime import datetime
from typing import List, Optional
from pydantic import UUID4
from pymongo import ASCENDING, DESCENDING
from app.models.learning import LearningRun, StartLearningRequest

COLLECTION = "learning_runs"

def init_indexes(db):
    col = db[COLLECTION]
    col.create_index([("workspace_id", ASCENDING), ("created_at", DESCENDING)])
    col.create_index([("run_id", ASCENDING)], unique=True)
    col.create_index([("status", ASCENDING)])
    col.create_index([("playbook_id", ASCENDING)])

def create_learning_run(db, req: StartLearningRequest, run_id: UUID4, *, pack_key: str, pack_version: str, playbook_id: str) -> LearningRun:
    run = LearningRun(
        run_id=run_id,
        workspace_id=req.workspace_id,
        repo=req.repo,
        options=req.options or {},
        pack_key=pack_key,
        pack_version=pack_version,
        playbook_id=playbook_id,
        status="created",
    )
    db[COLLECTION].insert_one(run.model_dump(mode="json"))
    return run

def get_by_run_id(db, run_id: UUID4) -> Optional[LearningRun]:
    doc = db[COLLECTION].find_one({"run_id": str(run_id)})
    return LearningRun.model_validate(doc) if doc else None

def list_by_workspace(db, workspace_id: UUID4, limit: int = 50, offset: int = 0) -> List[LearningRun]:
    cur = (
        db[COLLECTION]
        .find({"workspace_id": str(workspace_id)})
        .sort("created_at", DESCENDING)
        .skip(offset)
        .limit(min(limit, 200))
    )
    return [LearningRun.model_validate(d) for d in cur]

def set_status(db, run_id: UUID4, status: str, **fields):
    db[COLLECTION].update_one(
        {"run_id": str(run_id)},
        {"$set": {"status": status, "updated_at": datetime.utcnow(), **fields}},
    )
