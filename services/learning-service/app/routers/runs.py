from __future__ import annotations

import hashlib
import orjson
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import UUID4

from app.clients.artifact_service import ArtifactServiceClient, ServiceClientError as ArtifactSvcError
from app.clients.capability_service import CapabilityServiceClient, ServiceClientError as CapSvcError
from app.db.runs import (
    append_notes_md,
    create_run,
    get_run,
    list_runs,
    set_run_summary_times,
)
from app.models.run import LearningRun, StartLearningRequest
from app.graphs.learning_graph import execute_run_by_id

router = APIRouter(prefix="/runs", tags=["runs"])


def _fingerprint(obj: Any) -> str:
    data = orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(data).hexdigest()


@router.post("", response_model=LearningRun)
async def start_run(req: StartLearningRequest, request: Request, background: BackgroundTasks) -> LearningRun:
    """
    Initialize a learning run record and launch execution in a background task.
    """
    correlation_id = request.headers.get("X-Correlation-ID")

    # Validate the pack exists (resolved snapshot is what the agent will use)
    try:
        async with CapabilityServiceClient() as caps:
            _ = await caps.get_resolved_pack(req.pack_id, correlation_id=correlation_id)
    except CapSvcError as sce:
        raise HTTPException(status_code=sce.status, detail=f"capability-service error: {sce.body}") from sce
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Determine baseline vs delta
    strategy = (req.options.strategy_hint if req.options else None) or "baseline"
    try:
        async with ArtifactServiceClient() as arts:
            parent = await arts.get_workspace_parent(req.workspace_id, correlation_id=correlation_id)
            artifacts = parent.get("artifacts") or parent.get("items") or []
            strategy = "delta" if len(artifacts) > 0 else "baseline"
    except ArtifactSvcError:
        strategy = (req.options.strategy_hint if req.options else None) or "baseline"
    except Exception:
        strategy = (req.options.strategy_hint if req.options else None) or "baseline"

    # Compute input fingerprint
    input_fp = _fingerprint(req.inputs.model_dump())

    run = LearningRun(
        workspace_id=req.workspace_id,
        pack_id=req.pack_id,
        playbook_id=req.playbook_id,
        strategy=strategy,
        title=req.title,
        description=req.description,
        inputs=req.inputs,
        options=req.options or {},
        input_fingerprint=input_fp,
        status="created",
        run_summary=None,
    )

    # Persist
    await create_run(run)

    # Seed notes header
    header = (
        f"# Learning Run\n"
        f"- **Run ID**: {run.run_id}\n"
        f"- **Workspace**: {run.workspace_id}\n"
        f"- **Pack**: {run.pack_id}\n"
        f"- **Playbook**: {run.playbook_id}\n"
        f"- **Strategy**: {run.strategy}\n\n"
    )
    await append_notes_md(run.run_id, header)

    # Launch execution in background (non-blocking for the API caller)
    background.add_task(execute_run_by_id, run.run_id, correlation_id=correlation_id)

    return run


@router.get("/{run_id}", response_model=LearningRun)
async def get_run_by_id(run_id: UUID4) -> LearningRun:
    run = await get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@router.get("", response_model=List[LearningRun])
async def list_learning_runs(
    workspace_id: Optional[UUID4] = Query(default=None),
    status: Optional[str] = Query(default=None),
    pack_id: Optional[str] = Query(default=None),
    playbook_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    skip: int = Query(default=0, ge=0),
) -> List[LearningRun]:
    return await list_runs(
        workspace_id=workspace_id,
        status=status,
        pack_id=pack_id,
        playbook_id=playbook_id,
        limit=limit,
        skip=skip,
    )


@router.get("/{run_id}/notes", response_model=Dict[str, Any])
async def get_run_notes(run_id: UUID4) -> Dict[str, Any]:
    run = await get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return {"run_id": run.run_id, "notes_md": run.notes_md or ""}
