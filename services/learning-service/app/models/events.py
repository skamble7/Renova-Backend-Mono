from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional, List
from pydantic import BaseModel, UUID4, Field


# ─────────────────────────────────────────────────────────────
# Base envelope (kept for parity with existing code)
# ─────────────────────────────────────────────────────────────
class Event(BaseModel):
    type: str
    workspace_id: str
    payload: Any


# ─────────────────────────────────────────────────────────────
# Canonical learning RUN events (routing key: <org>.learning.<event>.v1)
# ─────────────────────────────────────────────────────────────

class LearningRunStarted(BaseModel):
    event: Literal["learning.run.started"] = "learning.run.started"
    run_id: UUID4
    workspace_id: UUID4
    pack_id: Optional[str] = None
    playbook_id: str
    strategy: Literal["baseline", "delta"]
    # standardized fields for starter payload
    model_id: Optional[str] = None
    received_at: datetime = Field(default_factory=datetime.utcnow)
    title: Optional[str] = None
    description: Optional[str] = None


class LearningRunCompleted(BaseModel):
    event: Literal["learning.run.completed"] = "learning.run.completed"
    run_id: UUID4
    workspace_id: UUID4
    playbook_id: str
    # Final (A) payload shape parity
    artifact_ids: List[str] = Field(default_factory=list)
    validations: List[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: datetime = Field(default_factory=datetime.utcnow)
    duration_s: float
    title: Optional[str] = None
    description: Optional[str] = None


class LearningRunCompletedInterim(BaseModel):
    """
    Interim 'completed' payload (B) after persist but before final summary.
    Mirrors your reference shape with deltas.counts.
    """
    event: Literal["learning.run.completed.interim"] = "learning.run.completed.interim"
    run_id: UUID4
    workspace_id: UUID4
    playbook_id: str
    artifact_ids: List[str] = Field(default_factory=list)
    artifact_failures: List[str] = Field(default_factory=list)
    validations: List[str] = Field(default_factory=list)
    deltas: Dict[str, Dict[str, int]] = Field(default_factory=lambda: {"counts": {}})


class LearningRunFailed(BaseModel):
    event: Literal["learning.run.failed"] = "learning.run.failed"
    run_id: UUID4
    workspace_id: UUID4
    error: str
    logs: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    artifact_failures: List[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    failed_at: datetime = Field(default_factory=datetime.utcnow)
    title: Optional[str] = None
    description: Optional[str] = None
    strategy: Optional[Literal["baseline", "delta"]] = None


# ─────────────────────────────────────────────────────────────
# Canonical learning STEP events
#   - We emit a generic "step" alongside specific "step.*"
# ─────────────────────────────────────────────────────────────

class StepInfo(BaseModel):
    id: str
    capability_id: Optional[str] = None
    name: Optional[str] = None


class StepBasePayload(BaseModel):
    run_id: UUID4
    workspace_id: UUID4
    playbook_id: str
    step: StepInfo
    params: Dict[str, Any] = Field(default_factory=dict)
    produces_kinds: List[str] = Field(default_factory=list)


class LearningStepStarted(StepBasePayload):
    status: Literal["started"] = "started"
    started_at: datetime = Field(default_factory=datetime.utcnow)


class LearningStepCompleted(StepBasePayload):
    status: Literal["completed"] = "completed"
    started_at: datetime
    ended_at: datetime = Field(default_factory=datetime.utcnow)
    duration_s: float


class LearningStepFailed(StepBasePayload):
    status: Literal["failed"] = "failed"
    started_at: datetime
    ended_at: datetime = Field(default_factory=datetime.utcnow)
    duration_s: float
    error: str
