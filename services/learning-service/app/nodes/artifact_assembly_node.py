# services/learning-service/app/nodes/artifact_assembly_node.py
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.models.state import LearningState

logger = logging.getLogger("app.nodes.artifact_assembly")

def _kinds(items: List[dict]) -> List[str]:
    return sorted({(a or {}).get("kind", "") for a in items if isinstance(a, dict)})

async def artifact_assembly_node(state: LearningState) -> LearningState:
    """
    Optional shaping stage after tools and before agents.
    MVP: pass-through (no-op).
    """
    artifacts: List[Dict[str, Any]] = list(state.get("artifacts") or [])
    logger.info("artifact_assembly.pass_through", extra={"count": len(artifacts), "kinds": _kinds(artifacts)})
    return {
        "artifacts": artifacts,
        "logs": ["artifact_assembly: pass-through"],
    }
