# services/learning-service/app/executor/executor.py
from __future__ import annotations
from typing import Any, Dict, List
import logging
from app.executor.runtime import make_runtime_config
from app.executor.tool_runner import run_tool
from app.clients import artifact_service

log = logging.getLogger("app.executor.executor")

async def _persist(workspace_id: str, run_id: str, generated: List[Dict[str, Any]]) -> List[str]:
    if not generated:
        return []
    items = []
    for g in generated:
        k = (g.get("kind") or "").strip() or "cam.document"
        n = (g.get("name") or k).strip()
        items.append({
            "kind": k,
            "name": n,
            "data": g.get("data"),
            "natural_key": f"{k}:{n}".lower(),
            "provenance": {"author": "learning-service", "run_id": run_id},
            "tags": ["generated", "learning"],
        })
    resp = await artifact_service.upsert_batch(workspace_id, items, run_id=run_id)
    ids: List[str] = []
    if isinstance(resp, dict):
        for r in resp.get("results") or []:
            aid = r.get("artifact_id") or r.get("id") or (r.get("artifact") or {}).get("_id")
            if aid:
                ids.append(str(aid))
    log.info("persist.batch", extra={"count": len(ids)})
    return ids

def _requires_satisfied(snapshot: Dict[str, Any], required_kinds: List[str]) -> bool:
    if not required_kinds:
        return True
    arts = snapshot.get("artifacts") or []
    present = {a.get("kind") for a in arts if isinstance(a, dict)}
    return all(k in present for k in required_kinds)

async def execute_playbook(*, workspace_id: str, workspace_name: str, playbook: Dict[str, Any], tool_params: Dict[str, Any], run_id: str) -> Dict[str, Any]:
    """
    (Legacy single-file executor – kept for parity)
    """
    logs: List[str] = []
    runtime = make_runtime_config(workspace_name)
    snapshot = await artifact_service.get_workspace_with_artifacts(workspace_id, include_deleted=False)

    generated_ids: List[str] = []
    for step in (playbook.get("steps") or []):
        sid = step.get("id") or step.get("capability") or "step"
        cap = step.get("capability") or ""
        requires = [r for r in (step.get("requires_kinds") or []) if isinstance(r, str)]

        if not _requires_satisfied(snapshot, requires):
            msg = f"gate.skip {sid}: requires={requires} not satisfied"
            logs.append(msg)
            log.info("execute_playbook.gate", extra={"step": sid, "requires": requires, "result": "skip"})
            continue

        params = dict(step.get("params") or {})
        if cap in ("tool.scm.checkout",):
            if "repo_path" not in params and tool_params.get("repo_path"):
                params["repo_path"] = tool_params["repo_path"]

        if cap == "tool.scm.clone":
            params.setdefault("repo_url", tool_params.get("repo_url"))
            params.setdefault("ref", tool_params.get("ref", "main"))
            params.setdefault("depth", tool_params.get("depth", 1))
            params.setdefault("sparse_globs", tool_params.get("sparse_globs", []))

        try:
            log.info("execute_playbook.step", extra={"step": sid, "cap": cap})
            arts, tlogs, _extras = await run_tool(cap, params, runtime)
            logs.extend([f"{sid}: {m}" for m in tlogs])

            if arts:
                ids = await _persist(workspace_id, run_id, arts)
                generated_ids.extend(ids)
                logs.append(f"{sid}: persisted={len(ids)}")
        except Exception as e:
            logs.append(f"{sid}: ERROR {e}")
            log.exception("execute_playbook.step_error", extra={"step": sid})

    return {"artifact_ids": generated_ids, "logs": logs}
