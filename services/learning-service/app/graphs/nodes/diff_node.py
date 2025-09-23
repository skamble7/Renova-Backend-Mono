# services/learning-service/app/graphs/nodes/diff_node.py
from __future__ import annotations

import copy
from typing import Any, Dict, List

from app.models.run import ArtifactsDiffBuckets, RunDeltas
from app.db.runs import set_diffs


def _key(kind_id: str, identity: Dict[str, Any]) -> str:
    return f"{kind_id}::{repr(sorted(identity.items()))}"


def _index_by_key(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    idx: Dict[str, Dict[str, Any]] = {}
    for e in items:
        k = _key(e["kind_id"], e["identity"])
        idx[k] = e
    return idx


def _deep_equal(a: Any, b: Any) -> bool:
    # Simplistic deep equal; callers are responsible for pruning volatile fields beforehand
    return a == b


async def diff_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Compute diffs vs baseline:
      - added: in produced but not in baseline
      - changed: present in both but content differs
      - unchanged: present in both and equal
      - removed: (only finalized later across all kinds, but we compute per kind here as well)
    Writes state['diffs_by_kind'] and aggregates counts in state['deltas'].
    """
    produced = state.get("produced", {})
    baseline = state.get("baseline", {})  # baseline artifacts are raw; assume shape similar enough

    diffs_by_kind: Dict[str, Any] = state.get("diffs_by_kind", {})
    counts = state.get("deltas", {}).get("counts", {})

    # Index baseline per kind by identity
    baseline_idx: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for kind_id, items in (baseline or {}).items():
        # Normalize baseline into ArtifactEnvelope-like dicts if needed
        envs = []
        for a in items:
            data = a.get("data") or a.get("payload") or a
            identity = a.get("identity") or {}
            schema_version = a.get("schema_version") or a.get("version") or "1.0.0"
            envs.append({"kind_id": kind_id, "schema_version": schema_version, "identity": identity, "data": data})
        baseline_idx[kind_id] = _index_by_key(envs)

    for kind_id, items in (produced or {}).items():
        # items are already envelopes
        prod_idx = _index_by_key(items)
        bl_idx = baseline_idx.get(kind_id, {})

        added, changed, unchanged = [], [], []
        # added/changed/unchanged
        for k, env in prod_idx.items():
            if k not in bl_idx:
                added.append(env)
            else:
                before = bl_idx[k]
                if _deep_equal(before.get("data"), env.get("data")):
                    unchanged.append(env)
                else:
                    changed.append({"kind_id": kind_id, "identity": env["identity"], "before": before["data"], "after": env["data"]})

        # removed
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
