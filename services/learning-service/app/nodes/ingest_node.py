# services/learning-service/app/nodes/ingest_node.py
from __future__ import annotations
from app.models.state import LearningState
from app.clients.capability_registry import get_pack_and_playbook
from app.config import settings

async def ingest_node(state: LearningState) -> LearningState:
    pack_key = state.get("pack_key") or settings.PACK_KEY
    pack_version = state.get("pack_version") or settings.PACK_VERSION
    playbook_id = state.get("playbook_id") or settings.PLAYBOOK_ID

    resolved = await get_pack_and_playbook(pack_key=pack_key, pack_version=pack_version, playbook_id=playbook_id)
    state.setdefault("context", {})["pack"] = resolved["pack"]
    state["plan"] = {"steps": list(resolved["playbook"].get("steps") or [])}
    state.setdefault("logs", []).append(f"ingest: loaded playbook {playbook_id} from {pack_key}/{pack_version}")
    return state
