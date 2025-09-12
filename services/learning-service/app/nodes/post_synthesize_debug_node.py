# services/learning-service/app/nodes/post_synthesize_debug_node.py
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List

from app.models.state import LearningState

log = logging.getLogger("app.nodes.post_synthesize_debug")

def _kinds(items: List[dict]) -> List[str]:
    return sorted({(a or {}).get("kind", "") for a in items if isinstance(a, dict)})

async def post_synthesize_debug_node(state: LearningState) -> LearningState:
    """
    Pure-debug snapshot right after agent synthesis.
    - Logs totals, per-kind counts, and a few sample names per kind.
    - Appends human-readable lines into state.logs (visible downstream).
    """
    arts: List[Dict[str, Any]] = list(state.get("artifacts") or [])
    by_kind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for a in arts:
        k = (a.get("kind") or "").strip()
        if k:
            by_kind[k].append(a)

    counts = {k: len(v) for k, v in by_kind.items()}
    samples = {
        k: [str((it.get("name") or "")).strip() or "<noname>" for it in v[:3]]
        for k, v in by_kind.items()
    }

    log.info(
        "post_synthesize_debug.summary",
        extra={"total": len(arts), "counts": counts, "samples": samples},
    )

    # Visible lines that end up in the run's logs
    lines: List[str] = []
    lines.append(f"post_synthesize: total={len(arts)} kinds={_kinds(arts)}")
    for k in sorted(counts.keys()):
        lines.append(f"post_synthesize: {k}={counts[k]} samples={samples[k]}")

    return {"logs": lines}
