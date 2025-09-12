# services/learning-service/app/nodes/publish_node.py
from __future__ import annotations
import logging
from app.models.state import LearningState
from app.infra.rabbit import publish_event_v1
from app.config import settings

log = logging.getLogger("app.nodes.publish")

async def publish_node(state: LearningState) -> LearningState:
    payload = {
        "run_id": state.get("context", {}).get("run_id"),
        "workspace_id": state.get("workspace_id"),
        "artifact_ids": list(state.get("run_artifact_ids") or []),
        "deltas": state.get("deltas") or {"counts": {}},
        "artifacts_diff": state.get("artifacts_diff") or {},
    }
    log.info("publish.event", extra={"artifact_ids": len(payload["artifact_ids"]), "workspace_id": payload["workspace_id"]})
    publish_event_v1(org=settings.EVENTS_ORG, event="completed", payload=payload, headers={})
    return state
