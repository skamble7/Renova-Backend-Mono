from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field, UUID4

# Inputs needed for learning
class RepoSpec(BaseModel):
    repo_url: str
    ref: Optional[str] = "main"
    sparse_globs: List[str] = Field(default_factory=lambda: ["**/*.cbl","**/*.cpy","**/*.jcl","**/*.ddl"])
    depth: int = 1  # 1 = shallow clone, 0 = full

class LearningOptions(BaseModel):
    pack_key: Optional[str] = None
    pack_version: Optional[str] = None
    playbook_id: Optional[str] = None
    dry_run: bool = False

class StartLearningRequest(BaseModel):
    workspace_id: UUID4
    repo: RepoSpec
    options: Optional[LearningOptions] = None

    # Optional metadata
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)

class RunSummary(BaseModel):
    artifact_ids: List[str] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_s: Optional[float] = None
    title: Optional[str] = None
    description: Optional[str] = None

class LearningRun(BaseModel):
    run_id: UUID4
    workspace_id: UUID4

    # Pack/playbook wiring resolved at start
    pack_key: str
    pack_version: str
    playbook_id: str

    repo: RepoSpec
    options: LearningOptions = Field(default_factory=LearningOptions)

    # Executor state
    status: Literal["created","running","completed","failed","aborted"] = "created"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Outputs
    run_summary: Optional[RunSummary] = None
    artifacts_diff: Optional[Dict[str, Any]] = None   # future: classification vs baseline if needed
