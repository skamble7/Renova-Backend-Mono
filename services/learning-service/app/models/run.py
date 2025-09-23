from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, UUID4, ConfigDict


# ─────────────────────────────────────────────────────────────
# Inputs for modernization learning runs
# ─────────────────────────────────────────────────────────────

class GitRepoSpec(BaseModel):
    """
    Minimal repo descriptor for modernization inputs.
    Supports a single repo or multiple (monorepo / multi-source).
    """
    url: HttpUrl | str
    revision: Optional[str] = Field(
        default=None, description="Branch/tag/commit; defaults to service/tool choice (e.g., 'main')."
    )
    subdir: Optional[str] = Field(
        default=None, description="Optional path to a subdirectory within the repo to scope analysis."
    )
    shallow: bool = Field(default=True, description="Allow shallow clone if supported by the MCP.")
    include_globs: List[str] = Field(default_factory=list, description="Optional file include patterns.")
    exclude_globs: List[str] = Field(default_factory=list, description="Optional file exclude patterns.")


class LearningInputs(BaseModel):
    """
    Primary inputs for a learning run.
    Additional arbitrary context is allowed for future-proofing.
    """
    repos: List[GitRepoSpec] = Field(default_factory=list)
    extra_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form hints (e.g., domain tags, known systems, constraints) used to enrich prompts."
    )


class LearningOptions(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # rename to avoid shadowing BaseModel.validate
    validate_: bool = Field(True, alias="validate")
    strict_json: bool = True
    dry_run: bool = False
    allow_partial_step_failures: bool = False
    model: str | None = None
    strategy_hint: str | None = None


class StartLearningRequest(BaseModel):
    """
    API request to start a learning run.
    We use a single `pack_id` (key@version) to avoid cross-field ambiguity.
    """
    playbook_id: str
    pack_id: str                       # e.g., "cobol-mainframe@v1.0"
    workspace_id: UUID4

    inputs: LearningInputs
    options: Optional[LearningOptions] = None

    # Friendly metadata for the run
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)


# ─────────────────────────────────────────────────────────────
# Artifact envelope, diffs & audit
# ─────────────────────────────────────────────────────────────

class ArtifactProvenance(BaseModel):
    run_id: UUID4
    step_id: str
    capability_id: str
    mode: Literal["mcp", "llm"]
    inputs_hash: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ArtifactEnvelope(BaseModel):
    """
    Canonical produced artifact with identity & schema version.
    """
    kind_id: str                       # cam.<category>.<kind>
    schema_version: str
    identity: Dict[str, Any]           # natural key fields per kind's identity rule
    data: Dict[str, Any]               # payload validated against json_schema
    provenance: ArtifactProvenance


class ChangedArtifact(BaseModel):
    kind_id: str
    identity: Dict[str, Any]
    before: Dict[str, Any]
    after: Dict[str, Any]


class ArtifactsDiffBuckets(BaseModel):
    """
    Diff buckets for a single kind.
    """
    added: List[ArtifactEnvelope] = Field(default_factory=list)
    changed: List[ChangedArtifact] = Field(default_factory=list)
    unchanged: List[ArtifactEnvelope] = Field(default_factory=list)
    removed: List[ArtifactEnvelope] = Field(default_factory=list)


class RunDeltas(BaseModel):
    """
    Aggregated counts derived from diffs.
    Keys: added, changed, unchanged, removed
    """
    counts: Dict[str, int] = Field(default_factory=dict)


class ValidationIssue(BaseModel):
    artifact_key: Dict[str, Any] = Field(
        default_factory=dict, description="At minimum: {kind_id, identity:{...}}"
    )
    severity: Literal["low", "medium", "high"] = "medium"
    message: str


class ToolCallAudit(BaseModel):
    """
    Captures MCP tool execution or LLM prompt exchange for audit.
    Exactly one of (tool_name, llm_prompt) should be present depending on mode.
    """
    # MCP
    tool_name: Optional[str] = None
    tool_args_preview: Optional[Dict[str, Any]] = None
    # LLM
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    llm_config: Optional[Dict[str, Any]] = None

    # Shared
    raw_output_sample: Optional[str] = Field(
        default=None, description="Truncated sample of raw output for troubleshooting."
    )
    validation_errors: List[str] = Field(default_factory=list)
    duration_ms: Optional[int] = None
    status: Literal["ok", "retried", "failed"] = "ok"


class StepAudit(BaseModel):
    step_id: str
    capability_id: str
    mode: Literal["mcp", "llm"]
    inputs_preview: Dict[str, Any] = Field(default_factory=dict)
    calls: List[ToolCallAudit] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Run persistence shape
# ─────────────────────────────────────────────────────────────

class RunSummary(BaseModel):
    validations: List[ValidationIssue] = Field(default_factory=list)
    logs: List[str] = Field(default_factory=list)
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_s: Optional[float] = None


class LearningRun(BaseModel):
    """
    Persistent record of a learning run.
    """
    run_id: UUID4 = Field(default_factory=uuid4)

    workspace_id: UUID4
    pack_id: str
    playbook_id: str

    # Run intent (the service may compute this if not hinted)
    strategy: Literal["baseline", "delta"] = "delta"

    # Friendly metadata
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)

    # Inputs & execution options
    inputs: LearningInputs
    options: LearningOptions = Field(default_factory=LearningOptions)

    # Input identity & comparison vs workspace baseline
    input_fingerprint: Optional[str] = None  # sha256 over canonical(inputs)
    input_diff: Optional[Dict[str, Any]] = None  # reserved for future (if we diff inputs over time)

    # Artifacts produced in this run
    run_artifacts: List[ArtifactEnvelope] = Field(default_factory=list)

    # Diffs vs prior baseline snapshot, organized per kind
    diffs_by_kind: Dict[str, ArtifactsDiffBuckets] = Field(default_factory=dict)
    deltas: Optional[RunDeltas] = None

    # Human-readable notes (Markdown) + full step audit trail
    notes_md: Optional[str] = None
    audit: List[StepAudit] = Field(default_factory=list)

    status: Literal["created", "running", "completed", "failed", "aborted"] = "created"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Minimal, non-redundant summary
    run_summary: Optional[RunSummary] = None
