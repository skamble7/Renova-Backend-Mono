from __future__ import annotations

from typing import Any, Dict, List, Literal, TypedDict
from pydantic import UUID4


class LearningState(TypedDict, total=False):
    """
    LangGraph state bag — single source of truth during a run.
    Keep this lightweight & JSON-serializable.
    """
    # Run scaffolding
    run_id: UUID4
    workspace_id: UUID4
    pack_id: str
    playbook_id: str
    strategy: Literal["baseline", "delta"]

    # Request inputs & options (already validated by models.run)
    inputs: Dict[str, Any]
    options: Dict[str, Any]

    # Baseline snapshot fetched from artifact-service (read-only)
    baseline: Dict[str, List[Dict[str, Any]]]  # kind_id -> [ArtifactEnvelope-like dicts]
    baseline_meta: Dict[str, Any]

    # Produced artifacts in this run (pre-persist)
    produced: Dict[str, List[Dict[str, Any]]]  # kind_id -> [ArtifactEnvelope-like dicts]

    # Step-local buffers (used by nodes, cleared between steps)
    last_output: List[Dict[str, Any]]
    last_validated: List[Dict[str, Any]]
    last_stats: Dict[str, Any]

    # Diffs & deltas (rolling as steps complete)
    diffs_by_kind: Dict[str, Dict[str, Any]]   # kind_id -> ArtifactsDiffBuckets-like dict
    deltas: Dict[str, Any]                     # {counts:{added,changed,unchanged,removed}}

    # Audit & reporting
    audit: List[Dict[str, Any]]                # step-level audit entries
    notes_md: str                              # incremental markdown
    logs: List[str]
    errors: List[str]

    # Planner/metadata/context bundle for depends_on
    context: Dict[str, Any]                    # e.g., map of kind_id -> artifacts referenced for context
