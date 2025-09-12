# services/learning-service/app/nodes/ingest_node.py
from __future__ import annotations
import logging
from app.models.state import LearningState
from app.clients.capability_registry import get_pack_and_playbook
from app.config import settings

log = logging.getLogger("app.nodes.ingest")

async def ingest_node(state: LearningState) -> LearningState:
    pack_key = state.get("pack_key") or settings.PACK_KEY
    pack_version = state.get("pack_version") or settings.PACK_VERSION
    playbook_id = state.get("playbook_id") or settings.PLAYBOOK_ID

    log.info("ingest.request", extra={"pack_key": pack_key, "pack_version": pack_version, "playbook_id": playbook_id})
    resolved = await get_pack_and_playbook(
        pack_key=pack_key,
        pack_version=pack_version,
        playbook_id=playbook_id,
    )
    log.info("ingest.result", extra={"steps": len(resolved["playbook"].get("steps") or [])})

    return {
        "context": {"pack": resolved["pack"]},
        "plan": {"steps": list(resolved["playbook"].get("steps") or [])},
        "logs": [f"ingest: loaded playbook {playbook_id} from {pack_key}/{pack_version}"],
    }
