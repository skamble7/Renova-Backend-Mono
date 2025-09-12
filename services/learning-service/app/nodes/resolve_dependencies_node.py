# services/learning-service/app/nodes/resolve_dependencies_node.py
from __future__ import annotations
from typing import Dict, Any, List, Set
import logging
from app.models.state import LearningState
from app.clients import artifact_service

log = logging.getLogger("app.nodes.resolve_dependencies")

def _collect_emitted_kinds(steps: List[dict]) -> List[str]:
    kinds: Set[str] = set()
    for s in steps or []:
        for k in s.get("emits") or []:
            if isinstance(k, str) and k:
                kinds.add(k)
    return sorted(kinds)

def _extract_dep_spec(kind_doc: Dict[str, Any]) -> Dict[str, Any]:
    svs = list(kind_doc.get("schema_versions") or [])
    if not svs:
        return {}
    latest = str(kind_doc.get("latest_schema_version") or "")
    pick = next((sv for sv in svs if str(sv.get("version")) == latest), svs[0])
    dep = pick.get("depends_on")
    if isinstance(dep, dict):
        hard = [k for k in dep.get("hard", []) if isinstance(k, str)]
        soft = [k for k in dep.get("soft", []) if isinstance(k, str)]
        hint = str(dep.get("context_hint") or "").strip()
        return {"hard": hard, "soft": soft, "context_hint": hint}
    if isinstance(dep, list):
        return {"hard": [k for k in dep if isinstance(k, str)], "soft": [], "context_hint": ""}
    return {}

async def resolve_dependencies_node(state: LearningState) -> LearningState:
    steps = list(state.get("plan", {}).get("steps") or [])
    if not steps:
        return {"dep_plan": {}, "logs": ["resolve_deps: no steps"]}

    emitted = _collect_emitted_kinds(steps)
    log.info("resolve_deps.state_in", extra={"steps": len(steps), "emitted_kinds": emitted})

    dep_plan: Dict[str, Dict[str, Any]] = {}

    try:
        resp = await artifact_service.get_kinds_by_keys(emitted)
        docs = {d.get("_id") or d.get("id"): d for d in (resp.get("items") or []) if isinstance(d, dict)}
    except Exception as e:
        log.warning("resolve_deps.registry_failed", extra={"error": str(e)})
        docs = {}

    for k in emitted:
        spec = _extract_dep_spec(docs.get(k) or {})
        dep_plan[k] = spec or {"hard": [], "soft": [], "context_hint": ""}

    log.info("resolve_deps.done", extra={"kinds": emitted, "non_empty": sum(1 for v in dep_plan.values() if (v.get('hard') or v.get('soft')))})
    return {"dep_plan": dep_plan, "logs": ["resolve_deps: built dep plan"]}
