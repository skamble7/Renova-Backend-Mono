from __future__ import annotations

import hashlib
import orjson
from typing import Any, Dict, List, Optional

from app.clients.artifact_service import ArtifactServiceClient
from app.db.runs import append_run_artifacts
from app.models.run import ArtifactEnvelope, ArtifactProvenance


def _fingerprint(obj: Any) -> str:
    data = orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(data).hexdigest()


def _compute_identity(data: Dict[str, Any], kind_doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Uses the kind's identity rule (list of field names) to extract a natural key.
    Fallback: return {"hash": sha256(json)}.
    """
    ident: Dict[str, Any] = {}
    identity = None

    latest = kind_doc.get("latest_schema_version")
    for sv in (kind_doc.get("schema_versions") or []):
        if sv.get("version") == latest:
            identity = sv.get("identity")
            break
    if identity is None:
        identity = kind_doc.get("identity")

    if isinstance(identity, list) and identity:
        for k in identity:
            if k in data:
                ident[k] = data[k]

    return ident or {"hash": _fingerprint(data)}


async def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates `state['last_output']` using artifact-service, computes identity (or accepts provided),
    wraps into ArtifactEnvelope, and appends to `state['produced']`.

    - Respects options.allow_partial_step_failures (skip bad items vs. fail step).
    - Caches kind definitions per step to avoid repeated GETs.
    """
    workspace_id = state["workspace_id"]  # not used here but kept for context
    run_id = state["run_id"]
    idx = int(state.get("_step_index", 0))
    step = state["plan"]["steps"][idx]
    allow_partial = bool((state.get("options") or {}).get("allow_partial_step_failures", False))
    correlation_id: Optional[str] = state.get("correlation_id")

    produced_by_kind: Dict[str, List[Dict[str, Any]]] = state.get("produced", {})
    envelopes: List[ArtifactEnvelope] = []

    # Cache for kind defs within this step
    _kind_cache: Dict[str, Dict[str, Any]] = {}

    async with ArtifactServiceClient() as arts:
        for item in state.get("last_output", []):
            kind_id = item.get("kind") or item.get("kind_id")
            if not kind_id:
                # Skip untyped results
                if allow_partial:
                    (state.setdefault("errors", [])).append("validate_node: missing kind_id on output item")
                    continue
                else:
                    raise ValueError("validate_node: output item missing kind/kind_id")

            data = item.get("data") or {}
            version = str(
                item.get("schema_version")
                or (state.get("kind_schema_version", {}) or {}).get(kind_id, "1.0.0")
            )

            try:
                # 1) Schema validation
                await arts.validate_kind_data(
                    kind_id=kind_id, data=data, version=version, correlation_id=correlation_id
                )

                # 2) Fetch kind definition (cached)
                if kind_id not in _kind_cache:
                    _kind_cache[kind_id] = await arts.get_kind(kind_id, correlation_id=correlation_id)
                kind_def = _kind_cache[kind_id]

                # 3) Identity: prefer tool-provided identity if present & dict
                identity = item.get("identity")
                if not isinstance(identity, dict) or not identity:
                    identity = _compute_identity(data, kind_def)

                # 4) Build envelope
                env = ArtifactEnvelope(
                    kind_id=kind_id,
                    schema_version=version,
                    identity=identity,
                    data=data,
                    provenance=ArtifactProvenance(
                        run_id=run_id,
                        step_id=(step.get("id") or step.get("step_id") or f"step{idx+1}"),
                        capability_id=step.get("capability_id"),
                        mode=(step.get("execution_mode") or "llm"),
                        inputs_hash=state.get("input_fingerprint"),
                    ),
                )
                envelopes.append(env)
                produced_by_kind.setdefault(kind_id, []).append(env.model_dump())

            except Exception as e:
                if allow_partial:
                    (state.setdefault("errors", [])).append(f"validate_node: {kind_id} failed: {e}")
                    continue
                raise

    state["produced"] = produced_by_kind
    state["last_validated"] = [e.model_dump() for e in envelopes]

    # Append to run document incrementally for streaming UIs
    if envelopes:
        await append_run_artifacts(run_id, envelopes)

    return state
