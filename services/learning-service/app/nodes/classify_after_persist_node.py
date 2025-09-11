# services/learning-service/app/nodes/classify_after_persist_node.py
from __future__ import annotations
from typing import Any, Dict, List
from uuid import UUID as _UUID
from app.models.state import LearningState
from app.clients import artifact_service

def _nk(a: Dict[str, Any]) -> str:
    return (a.get("natural_key") or f"{a.get('kind')}:{a.get('name')}").lower().strip()

async def classify_after_persist_node(state: LearningState) -> LearningState:
    """
    Persist artifacts first (state['run_artifact_ids'] must be set by main) then compute authoritative
    diff vs last promoted baseline.
    """
    workspace_id = state.get("workspace_id")
    right_ids = list(state.get("run_artifact_ids") or [])

    # No baseline → everything new
    base_run_id = None
    try:
        parent = await artifact_service.get_workspace_parent(workspace_id)
        base_run_id = parent.get("last_promoted_run_id")
    except Exception:
        base_run_id = None

    right_docs = await artifact_service.get_artifacts_by_ids(workspace_id, right_ids or [])
    if not base_run_id:
        new_nks = sorted({_nk(a) for a in right_docs if isinstance(a, dict)})
        counts = {"new": len(new_nks), "updated": 0, "unchanged": 0, "retired": 0}
        state["artifacts_diff"] = {"new": new_nks, "updated": [], "unchanged": [], "retired": [], "counts": counts}
        state["deltas"] = {"counts": counts}
        state.setdefault("logs", []).append(f"classify: baseline-none new={len(new_nks)}")
        return state

    # Load baseline run artifact IDs, then fetch docs
    base = await artifact_service.get_run_doc(_UUID(str(base_run_id)))
    left_ids: List[str] = list((base or {}).get("run_summary", {}).get("artifact_ids") or [])
    left_docs = await artifact_service.get_artifacts_by_ids(workspace_id, left_ids or [])

    L = {_nk(a): a for a in left_docs if isinstance(a, dict)}
    R = {_nk(a): a for a in right_docs if isinstance(a, dict)}

    new_keys, upd_keys, same_keys, ret_keys = [], [], [], []
    def _id_fp(d: Dict[str, Any]) -> tuple[str, str]:
        return (str(d.get("artifact_id") or d.get("_id") or ""), str(d.get("fingerprint") or ""))

    for nk, r in R.items():
        l = L.get(nk)
        if not l:
            new_keys.append(nk); continue
        lid, lfp = _id_fp(l); rid, rfp = _id_fp(r)
        if (lid and rid and lid == rid) or (lfp and rfp and lfp == rfp):
            same_keys.append(nk)
        else:
            upd_keys.append(nk)

    for nk in L.keys():
        if nk not in R:
            ret_keys.append(nk)

    counts = {"new": len(new_keys), "updated": len(upd_keys), "unchanged": len(same_keys), "retired": len(ret_keys)}
    state["artifacts_diff"] = {"new": sorted(new_keys), "updated": sorted(upd_keys), "unchanged": sorted(same_keys), "retired": sorted(ret_keys), "counts": counts}
    state["deltas"] = {"counts": counts}
    state.setdefault("logs", []).append(f"classify: counts={counts}")
    return state
