from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel  # <-- missing import
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..db.mongodb import get_db
from ..services.plan_resolver import resolve_plan
from ..models.integrations import ExecutionPlan


router = APIRouter(prefix="/capability", tags=["resolve"])


class ResolveRequest(BaseModel):
    pack_key: str
    pack_version: str
    playbook_id: str
    workspace_id: str
    overrides: dict | None = None


@router.post("/resolve", response_model=ExecutionPlan, status_code=status.HTTP_201_CREATED)
async def resolve(req: ResolveRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    plan = await resolve_plan(
        db, req.pack_key, req.pack_version, req.playbook_id, req.workspace_id, req.overrides or {}
    )
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pack or playbook not found")
    return plan
