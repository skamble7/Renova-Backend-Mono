from __future__ import annotations
import logging
import pymongo
from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Query
from fastapi.responses import ORJSONResponse
from pydantic import UUID4
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any, List

from app.config import settings
from app.logging import setup_logging
from app.middleware.correlation import CorrelationIdMiddleware, CorrelationIdFilter
from app.models.learning import StartLearningRequest, RunSummary
from app.db.learning_runs import init_indexes, create_learning_run, get_by_run_id, list_by_workspace, set_status
from app.graphs.learning_graph import build_graph
from app.clients import artifact_service
from app.infra.rabbit import publish_event_v1

logger = setup_logging()
app = FastAPI(default_response_class=ORJSONResponse, title=settings.SERVICE_NAME)
app.add_middleware(CorrelationIdMiddleware)
_corr_filter = CorrelationIdFilter()
for _n in ("", "uvicorn", "uvicorn.access", "uvicorn.error", "app"):
    logging.getLogger(_n).addFilter(_corr_filter)

def get_db():
    client = pymongo.MongoClient(settings.MONGO_URI, tz_aware=True)
    return client[settings.MONGO_DB]

@app.on_event("startup")
def _startup():
    db = get_db()
    init_indexes(db)
    logger.info("Indexes initialized for learning_runs", extra={"service": settings.SERVICE_NAME})

@app.get("/health")
async def health():
    return {"ok": True, "service": settings.SERVICE_NAME, "env": settings.ENV}

async def _run_learning(req: StartLearningRequest, run_id: UUID4):
    start_ts = datetime.now(timezone.utc)
    db = get_db()
    set_status(db, run_id, "running")

    publish_event_v1(
        org=settings.EVENTS_ORG,
        event="started",
        payload={
            "run_id": str(run_id),
            "workspace_id": str(req.workspace_id),
            "pack_key": (req.options.pack_key if req.options else None) or settings.PACK_KEY,
            "pack_version": (req.options.pack_version if req.options else None) or settings.PACK_VERSION,
            "playbook_id": (req.options.playbook_id if req.options else None) or settings.PLAYBOOK_ID,
            "repo_url": req.repo.repo_url,
            "received_at": start_ts.isoformat(),
            "title": req.title,
            "descri ption": req.description,
        },
        headers={},
    )

    state = {
        "workspace_id": str(req.workspace_id),
        "model_id": settings.MODEL_ID,
        "pack_key": (req.options.pack_key if req.options else None) or settings.PACK_KEY,
        "pack_version": (req.options.pack_version if req.options else None) or settings.PACK_VERSION,
        "playbook_id": (req.options.playbook_id if req.options else None) or settings.PLAYBOOK_ID,
        "repo": req.repo.model_dump(),
        "artifacts": [],
        "logs": [],
        "errors": [],
        "context": {"run_id": str(run_id)},
    }

    try:
        graph = build_graph()
        result = await graph.ainvoke(state)

        # ✅ Persist BEFORE classification (as requested)
        items = []
        for cam in (result.get("artifacts") or []):
            k = (cam.get("kind") or "cam.document").strip()
            n = (cam.get("name") or k).strip()
            items.append({
                "kind": k, "name": n, "data": cam.get("data"),
                "natural_key": f"{k}:{n}".lower(),
                "tags": ["generated","learning"],
                "provenance": {"author":"learning-service","run_id":str(run_id)},
            })
        saved_ids: List[str] = []
        if items:
            batch = await artifact_service.upsert_batch(str(req.workspace_id), items, run_id=str(run_id))
            for r in (batch.get("results") or []):
                aid = r.get("artifact_id") or r.get("id") or (r.get("artifact") or {}).get("_id")
                if aid: saved_ids.append(str(aid))

        # hand IDs back to state so classifier runs after persist
        result["run_artifact_ids"] = saved_ids

        # Re-run only the classification node on the enriched state
        from app.nodes.classify_after_persist_node import classify_after_persist_node
        result = await classify_after_persist_node(result)

        completed_at = datetime.now(timezone.utc)
        summary = RunSummary(
            artifact_ids=saved_ids,
            logs=list(result.get("logs") or []),
            started_at=start_ts,
            completed_at=completed_at,
            duration_s=(completed_at - start_ts).total_seconds(),
            title=req.title,
            description=req.description,
        )
        set_status(db, run_id, "completed", run_summary=summary.model_dump(mode="json"),
                   artifacts_diff=result.get("artifacts_diff"), deltas=result.get("deltas"))

        # Publish completion (node also publishes, but this carries summary)
        publish_event_v1(org=settings.EVENTS_ORG, event="completed",
                         payload={"run_id": str(run_id), "workspace_id": str(req.workspace_id), **summary.model_dump(mode="json"),
                                  "deltas": result.get("deltas"), "artifacts_diff": result.get("artifacts_diff")},
                         headers={})

    except Exception as e:
        logger.exception("learning_failed", extra={"run_id": str(run_id)})
        set_status(db, run_id, "failed", error=str(e))
        publish_event_v1(org=settings.EVENTS_ORG, event="failed",
                         payload={"run_id": str(run_id), "workspace_id": str(req.workspace_id), "error": str(e)}, headers={})

@app.post("/learn/{workspace_id}", status_code=202)
async def learn(workspace_id: str, req: StartLearningRequest, bg: BackgroundTasks, db=Depends(get_db)):
    if str(req.workspace_id) != workspace_id:
        raise HTTPException(status_code=400, detail="workspace_id in path and body must match")
    run_id = UUID4(str(uuid4()))
    _ = create_learning_run(db, req, run_id,
                            pack_key=(req.options.pack_key if req.options else None) or settings.PACK_KEY,
                            pack_version=(req.options.pack_version if req.options else None) or settings.PACK_VERSION,
                            playbook_id=(req.options.playbook_id if req.options else None) or settings.PLAYBOOK_ID)
    bg.add_task(_run_learning, req, run_id)
    return {"accepted": True, "run_id": str(run_id), "workspace_id": workspace_id, "message": "Learning started."}

@app.get("/runs/{run_id}")
async def get_run(run_id: UUID4, db=Depends(get_db)):
    run = get_by_run_id(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Learning run not found.")
    return run.model_dump(mode="json")

@app.get("/runs")
async def list_runs(workspace_id: UUID4 = Query(...), limit: int = 50, offset: int = 0, db=Depends(get_db)):
    runs = list_by_workspace(db, workspace_id, limit=limit, offset=offset)
    return [r.model_dump(mode="json") for r in runs]
