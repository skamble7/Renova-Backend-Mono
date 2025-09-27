# services/learning-service/app/graphs/nodes/diagram_node.py
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.clients.artifact_service import ArtifactServiceClient
from app.diagrams.generator import generate_diagrams_for_artifact

log = logging.getLogger("app.graphs.nodes.diagram")


def _env_key(env: Dict[str, Any]) -> tuple[str, str]:
    kind = str(env.get("kind_id") or env.get("kind") or "")
    ident = env.get("identity") or {}
    return kind, repr(sorted(ident.items()))


async def diagram_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    For each envelope validated in THIS step, generate Mermaid diagrams using only the
    recipe `view` and the full artifact JSON (templates ignored).
    """
    correlation_id: Optional[str] = state.get("correlation_id")
    run_id: Optional[str] = state.get("run_id")
    idx = int(state.get("_step_index", 0))
    plan = state.get("plan") or {}
    steps = plan.get("steps") or []
    step = steps[idx] if idx < len(steps) else {}
    llm_cfg = (step.get("capability_snapshot") or {}).get("llm_config") or {}

    last: List[Dict[str, Any]] = list(state.get("last_validated") or [])
    produced: Dict[str, List[Dict[str, Any]]] = state.get("produced") or {}

    if not last:
        log.debug("diagram_node.no_last_validated", extra={"run_id": run_id})
        return state

    kinds_needed = sorted({str(e.get("kind_id") or e.get("kind") or "") for e in last if (e.get("kind_id") or e.get("kind"))})
    kind_docs: Dict[str, Dict[str, Any]] = {}

    async with ArtifactServiceClient() as arts:
        for kid in kinds_needed:
            try:
                kd = await arts.get_kind(kid, correlation_id=correlation_id)
                kind_docs[kid] = kd
            except Exception as e:
                log.warning("diagram_node.kind_fetch_failed", extra={"kind_id": kid, "err": repr(e)})
                kind_docs[kid] = {}

    attach_count = 0
    for env in last:
        kind_id = str(env.get("kind_id") or env.get("kind") or "")
        art_name = str((env.get("identity") or {}).get("name") or env.get("name") or "")
        if not kind_id:
            log.debug("diagram_node.skip_env_no_kind", extra={"identity": env.get("identity")})
            continue

        data = env.get("data") or {}
        kind_doc = kind_docs.get(kind_id) or {}

        # pass a dump key so dump files are identifiable (if enabled)
        dump_key = f"{run_id or 'run'}_{kind_id.replace('.', '-')}_{art_name or 'artifact'}"
        diagrams = await generate_diagrams_for_artifact(
            kind_doc=kind_doc, data=data, llm_config=llm_cfg, dump_key=dump_key
        )
        if not diagrams:
            # IMPORTANT: avoid reserved key 'name' in logging 'extra'
            log.info("diagram_node.no_diagrams_for_env", extra={"kind_id": kind_id, "artifact_name": art_name})
            continue

        env["diagrams"] = diagrams
        attach_count += 1

        k1 = _env_key(env)
        mirrored = False
        for pe in produced.get(kind_id, []):
            if _env_key(pe) == k1:
                pe["diagrams"] = diagrams
                mirrored = True
                break

        log.info(
            "diagram_node.attached",
            extra={
                "kind_id": kind_id,
                "artifact_name": art_name,   # renamed to avoid LogRecord.name collision
                "count": len(diagrams),
                "mirrored": mirrored,
                "diagram_ids": [d.get("id") for d in diagrams],
            },
        )

    log.info("diagram_node.summary", extra={"envs": len(last), "attached": attach_count})
    state["last_validated"] = last
    state["produced"] = produced
    return state
