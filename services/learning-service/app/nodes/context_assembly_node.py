# services/learning-service/app/nodes/context_assembly_node.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, DefaultDict
from collections import defaultdict

from app.models.state import LearningState
from app.clients import artifact_service

logger = logging.getLogger("app.nodes.context_assembly")

# Safety caps to keep agent prompts manageable
MAX_ITEMS_PER_KIND = 25   # total items to attach per kind (hard or soft)

def _index_by_kind(items: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    byk: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for a in items or []:
        if not isinstance(a, dict):
            continue
        k = (a.get("kind") or "").strip()
        if k:
            byk[k].append(a)
    return dict(byk)

def _cap(v: List[Dict[str, Any]], n: int = MAX_ITEMS_PER_KIND) -> List[Dict[str, Any]]:
    return list(v or [])[:n]

async def context_assembly_node(state: LearningState) -> LearningState:
    """
    Materializes the inputs required by the dependency plan.
    """
    dep_plan: Dict[str, Dict[str, Any]] = dict(state.get("dep_plan") or {})
    produced_now: List[Dict[str, Any]] = list(state.get("artifacts") or [])
    workspace_id: str = str(state.get("workspace_id") or "")

    logger.info(
        "context_assembly.state_in",
        extra={
            "steps_in_dep_plan": len(dep_plan),
            "artifacts_now": len(produced_now),
            "workspace_id_present": bool(workspace_id),
        },
    )

    logs: List[str] = []
    related: Dict[str, Dict[str, Dict[str, List[Dict[str, Any]]]]] = {}
    hints: Dict[str, str] = {}

    # Index produced artifacts by kind
    by_kind_now = _index_by_kind(produced_now)

    # Fetch baseline once (best-effort)
    baseline_by_kind: Dict[str, List[Dict[str, Any]]] = {}
    try:
        if workspace_id:
            parent = await artifact_service.get_workspace_with_artifacts(workspace_id, include_deleted=False)
            baseline_items = list((parent or {}).get("artifacts") or [])
            baseline_by_kind = _index_by_kind(baseline_items)
            logger.info(
                "context_assembly.baseline_loaded",
                extra={"workspace_id": workspace_id, "items": len(baseline_items)},
            )
    except Exception as e:
        logger.info("context_assembly.baseline_fetch_failed", extra={"error": str(e)})
        logs.append("context_assembly: baseline fetch failed; using run outputs only")

    # Build per-step related context
    steps_with_ctx = 0
    for sid, plan in dep_plan.items():
        hard_kinds = list((plan or {}).get("hard") or [])
        soft_kinds = list((plan or {}).get("soft") or [])
        hint = (plan or {}).get("context_hint") or ""
        hints[sid] = str(hint)

        hard_map: Dict[str, List[Dict[str, Any]]] = {}
        soft_map: Dict[str, List[Dict[str, Any]]] = {}

        # Prefer run outputs; fallback to baseline; cap counts
        for k in hard_kinds:
            vals = list(by_kind_now.get(k) or []) or list(baseline_by_kind.get(k) or [])
            if vals:
                hard_map[k] = _cap(vals)

        for k in soft_kinds:
            vals = list(by_kind_now.get(k) or []) or list(baseline_by_kind.get(k) or [])
            if vals:
                soft_map[k] = _cap(vals)

        if hard_map or soft_map:
            steps_with_ctx += 1
        related[sid] = {"hard": hard_map, "soft": soft_map}

    logs.append(f"context_assembly: steps={len(dep_plan)} with_related={steps_with_ctx} cap={MAX_ITEMS_PER_KIND}/kind")
    logger.info("context_assembly.done", extra={"steps": len(dep_plan), "with_related": steps_with_ctx})
    return {
        "related": related,
        "hints": hints,
        "logs": logs,
    }
