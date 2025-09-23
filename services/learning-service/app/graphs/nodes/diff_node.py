# services/learning-service/app/graphs/nodes/diff_node.py
from __future__ import annotations

from typing import Any, Dict, List

from app.models.run import ArtifactsDiffBuckets
from app.db.runs import set_diffs


def _key(kind_id: str, identity: Dict[str, Any]) -> str:
    return f"{kind_id}::{repr(sorted((identity or {}).items()))}"


def _index_by_key(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for e in items:
        idx[_key(e["kind_id"], e.get("identity") or {})] = e
    return idx


def _deep_equal(a: Any, b: Any) -> bool:
    # Simplistic deep equal; callers are responsible for pruning volatile fields beforehand
    return a == b


def _baseline_envelope(kind_id: str, raw: Dict[str, Any], *, prov: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a baseline artifact (from parent/workspace) into our envelope shape.
    Ensures schema_version is a string and provenance is present.
    Accepts shapes like:
      {kind, kind_id, data|body|payload, schema_version|version, identity?, name?, tags?}
    """
    data = raw.get("data") or raw.get("body") or raw.get("payload") or raw
    schema_v = raw.get("schema_version", raw.get("version", "1.0.0"))
    # Coerce schema_version to string (artifact-service may store it as int)
    schema_v = str(schema_v)

    env: Dict[str, Any] = {
        "kind_id": kind_id,
        "schema_version": schema_v,
        "identity": raw.get("identity") or {},
        "data": data,
        "provenance": prov,
    }
    # Preserve optional niceties if present
    if "name" in raw:
        env["name"] = raw["name"]
    tags = raw.get("tags")
    if tags is not None:
        env["tags"] = tags if isinstance(tags, list) else [str(tags)]
    return env


async def diff_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute diffs vs baseline:
      - added: in produced but not in baseline
      - changed: present in both but content differs
      - unchanged: present in both and equal
      - removed: in baseline but not in produced
    Writes state['diffs_by_kind'] and aggregates counts in state['deltas'].
    """
    produced = state.get("produced", {})
    baseline = state.get("baseline", {})  # baseline artifacts are raw; normalize below

    diffs_by_kind: Dict[str, Any] = state.get("diffs_by_kind", {})
    counts = state.get("deltas", {}).get("counts", {})

    # Synthetic provenance for baseline envelopes (to satisfy envelope schema)
    baseline_prov = {
        "run_id": state.get("run_id"),
        "step_id": "baseline",
        "capability_id": "",   # must be a string per ArtifactProvenance
        "mode": "llm",         # must be one of the accepted literals ("mcp" | "llm")
        "inputs_hash": state.get("input_fingerprint"),
    }

    # Index baseline per kind by identity (normalized to envelope shape)
    baseline_idx: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for kind_id, items in (baseline or {}).items():
        envs: List[Dict[str, Any]] = []
        for a in (items or []):
            envs.append(_baseline_envelope(kind_id, a or {}, prov=baseline_prov))
        baseline_idx[kind_id] = _index_by_key(envs)

    # Walk produced kinds
    for kind_id, items in (produced or {}).items():
        prod_idx = _index_by_key(items or [])
        bl_idx = baseline_idx.get(kind_id, {})

        added, changed, unchanged = [], [], []

        # added / changed / unchanged
        for k, env in prod_idx.items():
            if k not in bl_idx:
                added.append(env)
            else:
                before = bl_idx[k]
                if _deep_equal(before.get("data"), env.get("data")):
                    # Keep the produced envelope (has proper provenance)
                    unchanged.append(env)
                else:
                    changed.append({
                        "kind_id": kind_id,
                        "identity": env.get("identity") or {},
                        "before": before.get("data"),
                        "after": env.get("data"),
                    })

        # removed (baseline present but not produced)
        removed = []
        for k, env in bl_idx.items():
            if k not in prod_idx:
                removed.append(env)

        bucket = ArtifactsDiffBuckets(
            added=added, changed=changed, unchanged=unchanged, removed=removed
        ).model_dump()
        diffs_by_kind[kind_id] = bucket

        # aggregate counts
        counts["added"] = counts.get("added", 0) + len(added)
        counts["changed"] = counts.get("changed", 0) + len(changed)
        counts["unchanged"] = counts.get("unchanged", 0) + len(unchanged)
        counts["removed"] = counts.get("removed", 0) + len(removed)

    state["diffs_by_kind"] = diffs_by_kind
    state["deltas"] = {"counts": counts}

    # Persist a snapshot of diffs for the run document (handy for UI)
    await set_diffs(state["run_id"], diffs_by_kind, None)
    return state
