from __future__ import annotations

import hashlib
import orjson
from typing import Any, Dict, List, Tuple

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
    ident = {}
    identity = None
    # Try schema_versions.latest first
    latest = kind_doc.get("latest_schema_version")
    for sv in (kind_doc.get("schema_versions") or []):
        if sv.get("version") == latest:
            identity = sv.get("identity")
            break
    # Fall back to top-level identity
    if identity is None:
        identity = kind_doc.get("identity")
    if isinstance(identity, list) and identity:
        for k in identity:
            if k in data:
                ident[k] = data[k]
    if ident:
        return ident
    return {"hash": _fingerprint(data)}


async def validate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates `state['last_output']` using artifact-service, computes identity,
    wraps into ArtifactEnvelope, and appends to `state['produced']`.
    """
    workspace_id = state["workspace_id"]
    run_id = state["run_id"]
    idx = state.get("_step_index", 0)
    step = state["plan"]["steps"][idx]

    correlation_id = state.get("correlation_id")

    produced_by_kind: Dict[str, List[Dict[str, Any]]] = state.get("produced", {})
    envelopes: List[ArtifactEnvelope] = []

    async with ArtifactServiceClient() as arts:
        for item in state.get("last_output", []):
            kind_id = item.get("kind") or item.get("kind_id")
            if not kind_id:
                # skip unknown item
                continue
            data = item.get("data") or {}
            version = str(item.get("schema_version") or state.get("kind_schema_version", {}).get(kind_id, "1.0.0"))

            # Validate
            await arts.validate_kind_data(kind_id=kind_id, data=data, version=version, correlation_id=correlation_id)
            kind_def = await arts.get_kind(kind_id, correlation_id=correlation_id)

            identity = _compute_identity(data, kind_def)
            env = ArtifactEnvelope(
                kind_id=kind_id,
                schema_version=version,
                identity=identity,
                data=data,
                provenance=ArtifactProvenance(
                    run_id=run_id,
                    step_id=step["step_id"],
                    capability_id=step["capability_id"],
                    mode=step["mode"],
                    inputs_hash=state.get("input_fingerprint"),
                ),
            )
            envelopes.append(env)
            produced_by_kind.setdefault(kind_id, []).append(env.model_dump())

    state["produced"] = produced_by_kind
    state["last_validated"] = [e.model_dump() for e in envelopes]

    # Optionally: append to run document incrementally (kept; makes UI streaming easier)
    if envelopes:
        await append_run_artifacts(run_id, envelopes)

    return state
