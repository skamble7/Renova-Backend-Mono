# services/learning-service/app/nodes/validate_node.py
from __future__ import annotations
from pathlib import Path
import json
import logging
from app.models.state import LearningState
from app.llms.registry import get_provider

logger = logging.getLogger("app.nodes.validate_node")
VAL_PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "validate.txt"

async def validate_node(state: LearningState) -> LearningState:
    artifacts = state.get("artifacts") or []
    if not artifacts:
        return {"logs": ["validation: skipped (no artifacts)"]}

    provider = get_provider(state.get("model_id"))
    system_text = VAL_PROMPT.read_text()
    user_payload = {"artifacts": artifacts}

    # Log small previews (don’t dump full artifacts)
    try:
        logger.info(
            "validation.request preview",
            extra={
                "count": len(artifacts),
                "sample_kinds": sorted({(a or {}).get("kind", "?") for a in artifacts})[:8],
            },
        )
    except Exception:
        pass

    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": json.dumps(user_payload, separators=(",", ":"))},
    ]
    try:
        content = await provider.chat_json(messages)
        result = json.loads(content) if isinstance(content, str) else (content or {})
        issues = list(result.get("issues", []))
        logger.info("validation.response", extra={"issues_count": len(issues), "bytes": len(content or "")})
        return {
            "context": {"validations": issues},
            "logs": [f"validation: {len(issues)} issues"],
        }
    except Exception as e:
        logger.exception("validate_node_parse_error")
        return {
            "context": {"validations": [{"severity": "info", "message": f"Validator non-JSON: {e}"}]},
            "logs": ["validation: 1 issues (fallback)"],
        }
