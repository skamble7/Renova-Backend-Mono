# services/learning-service/app/nodes/validate_node.py
from __future__ import annotations
from pathlib import Path
import json, logging
from app.models.state import LearningState
from app.llms.registry import get_provider

logger = logging.getLogger(__name__)
VAL_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "validate.txt"

async def validate_node(state: LearningState) -> LearningState:
    if not state.get("artifacts"):
        return state
    provider = get_provider(state.get("model_id"))
    messages = [
        {"role":"system", "content": VAL_PROMPT.read_text()},
        {"role":"user", "content": json.dumps({"artifacts": state["artifacts"]}, separators=(",",":"))}
    ]
    try:
        content = await provider.chat_json(messages)
        result = json.loads(content) if isinstance(content, str) else content
    except Exception as e:
        logger.exception("validate_node_parse_error")
        result = {"issues":[{"severity":"info","message":f"Validator non-JSON: {e}"}]}
    state.setdefault("context", {})["validations"] = result.get("issues", [])
    state.setdefault("logs", []).append(f"validation: {len(result.get('issues', []))} issues")
    return state
