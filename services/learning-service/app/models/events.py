from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Literal, Optional
from pydantic import BaseModel, UUID4, Field


# Base event envelope (topic routing handled by publisher)
class Event(BaseModel):
    type: str
    workspace_id: str
    payload: Any


# ─────────────────────────────────────────────────────────────
# Canonical learning events (emitted on RabbitMQ)
# ─────────────────────────────────────────────────────────────

class LearningRunStarted(BaseModel):
    event: Literal["learning.run.started"] = "learning.run.started"
    run_id: UUID4
    workspace_id: UUID4
    pack_id: str
    playbook_id: str
    strategy: Literal["baseline", "delta"]
    started_at: datetime = Field(default_factory=datetime.utcnow)
    title: Optional[str] = None


class LearningStepStarted(BaseModel):
    event: Literal["learning.step.started"] = "learning.step.started"
    run_id: UUID4
    workspace_id: UUID4
    step_id: str
    capability_id: str
    mode: Literal["mcp", "llm"]
    started_at: datetime = Field(default_factory=datetime.utcnow)


class LearningStepCompleted(BaseModel):
    event: Literal["learning.step.completed"] = "learning.step.completed"
    run_id: UUID4
    workspace_id: UUID4
    step_id: str
    capability_id: str
    mode: Literal["mcp", "llm"]
    status: Literal["ok", "retried", "failed"] = "ok"
    duration_ms: int
    produced_counts: Dict[str, int] = Field(
        default_factory=dict, description="Counts by kind produced within the step."
    )
    completed_at: datetime = Field(default_factory=datetime.utcnow)


class LearningRunCompleted(BaseModel):
    event: Literal["learning.run.completed"] = "learning.run.completed"
    run_id: UUID4
    workspace_id: UUID4
    pack_id: str
    playbook_id: str
    strategy: Literal["baseline", "delta"]
    status: Literal["completed", "failed", "aborted"]
    artifact_counts: Dict[str, int] = Field(
        default_factory=dict, description="Aggregate counts by kind across the run."
    )
    deltas_counts: Dict[str, int] = Field(
        default_factory=dict, description="Aggregate diff buckets: added/changed/unchanged/removed"
    )
    started_at: datetime
    completed_at: datetime = Field(default_factory=datetime.utcnow)
