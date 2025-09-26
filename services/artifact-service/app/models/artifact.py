# services/artifact-service/app/models/artifact.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, ConfigDict

# ─────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────
# Accept any registered kind; runtime validation will verify against registry
ArtifactKind = str


class Provenance(BaseModel):
    """
    Single, structured provenance record stamped on writes.
    In Renova, runs are 'relearning runs' mined from legacy code,
    but we keep fields generic to match RainaV2 parity.
    """
    run_id: Optional[str] = None           # relearning run id
    playbook_id: Optional[str] = None      # which playbook/capability pipeline
    model_id: Optional[str] = None         # LLM/tooling identity if applicable
    step: Optional[str] = None             # pipeline step/stage
    pack_key: Optional[str] = None
    pack_version: Optional[str] = None
    inputs_fingerprint: Optional[str] = None  # canonicalized inputs snapshot
    author: Optional[str] = None           # human author (if manual)
    agent: Optional[str] = None            # e.g., "learning_service"
    reason: Optional[str] = None           # short note
    source_repo: Optional[str] = None      # e.g., git URL
    source_ref: Optional[str] = None       # branch/tag
    source_commit: Optional[str] = None    # commit hash used for mining


class WorkspaceSnapshot(BaseModel):
    """Denormalized snapshot of the workspace, as known to artifact-service."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    id: str = Field(..., alias="_id")      # allow Mongo-style _id alias
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class Lineage(BaseModel):
    first_seen_run_id: Optional[str] = None
    last_seen_run_id: Optional[str] = None
    supersedes: List[str] = Field(default_factory=list)  # prior artifact_ids
    superseded_by: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# NEW: embedded diagram representations for an artifact
# ─────────────────────────────────────────────────────────────
class DiagramInstance(BaseModel):
    """
    A single diagram representation for this artifact.
    Multiple entries are allowed (e.g., flowchart, sequence, mindmap), possibly in different languages.
    """
    # Identity / classification
    recipe_id: Optional[str] = Field(
        default=None,
        description="Registry recipe id if applicable (e.g., 'program.sequence')."
    )
    view: Optional[str] = Field(
        default=None,
        description="High-level view type (e.g., 'flowchart','sequence','mindmap','activity','er')."
    )
    language: str = Field(
        default="mermaid",
        description="Diagram language to render with (e.g., mermaid, plantuml, d2, graphviz)."
    )

    # The actual diagram text to render
    instructions: str = Field(
        ...,
        description="Plain-text diagram instructions in the given language."
    )

    # Optional rendering hints (direction, theme, width/height, etc.)
    renderer_hints: Optional[Dict[str, Any]] = None

    # Traceability (for staleness checks)
    generated_from_fingerprint: Optional[str] = Field(
        default=None,
        description="Fingerprint of the artifact data this diagram was generated from."
    )
    prompt_rev: Optional[int] = Field(
        default=None,
        description="If produced by an LLM prompt recipe, record its prompt_rev."
    )
    provenance: Optional[Provenance] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ArtifactItem(BaseModel):
    """Embedded artifact stored inside the per-workspace parent document."""
    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: ArtifactKind
    name: str
    data: Dict[str, Any]

    # NEW: embedded diagram representations for this artifact
    diagrams: List[DiagramInstance] = Field(default_factory=list)

    # Identity & versioning
    natural_key: Optional[str] = None          # per-kind deterministic key
    fingerprint: Optional[str] = None          # sha256 over normalized *data only*
    diagram_fingerprint: Optional[str] = None  # sha256 over normalized diagrams array
    version: int = 1
    lineage: Optional[Lineage] = None

    # Timestamps / status
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None

    provenance: Optional[Provenance] = None


class ArtifactItemCreate(BaseModel):
    """Write payload used by learning-service (or UI) to add/upsert artifacts."""
    kind: ArtifactKind
    name: str
    data: Dict[str, Any]
    diagrams: Optional[List[DiagramInstance]] = None  # NEW
    natural_key: Optional[str] = None
    fingerprint: Optional[str] = None                # remains data-only
    provenance: Optional[Provenance] = None


class ArtifactItemReplace(BaseModel):
    # Allow replacing either data, diagrams, or both
    data: Optional[Dict[str, Any]] = None
    diagrams: Optional[List[DiagramInstance]] = None
    provenance: Optional[Provenance] = None


class ArtifactItemPatchIn(BaseModel):
    # RFC 6902 JSON Patch (applies to `.data` only)
    patch: List[Dict[str, Any]]
    provenance: Optional[Provenance] = None


class WorkspaceArtifactsDoc(BaseModel):
    """
    Single MongoDB document per workspace aggregating all artifacts + baseline.
    Kept RainaV2-compatible, but the 'baseline' here usually represents a
    *source snapshot* (e.g., repo/commit + config) for Renova.
    """
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")               # Mongo _id for this doc
    workspace_id: str                          # convenience for querying
    workspace: WorkspaceSnapshot

    # Baseline snapshot (Renova): source/repo state or mined-input snapshot
    baseline: Dict[str, Any] = Field(default_factory=dict)
    baseline_fingerprint: Optional[str] = None     # sha256 over canonical(baseline)
    baseline_version: int = 1
    last_promoted_run_id: Optional[str] = None

    artifacts: List[ArtifactItem] = Field(default_factory=list)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
