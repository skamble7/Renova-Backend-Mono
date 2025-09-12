# services/learning-service/app/nodes/plan_node.py
from __future__ import annotations
from typing import Dict, Any, List
from app.models.state import LearningState
from app.llms.registry import get_provider
import json, logging

log = logging.getLogger("app.nodes.plan_node")

def _clip(s: str, n: int = 2000) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."

def _norm_step(s: dict) -> dict:
    # keep ids and tool_key/capability_id; normalize optional lists
    return {
        "id": s.get("id"),
        "type": s.get("type"),
        "tool_key": s.get("tool_key"),
        "capability_id": s.get("capability_id"),
        "params": s.get("params") or {},
        "emits": s.get("emits") or [],
        "requires_kinds": s.get("requires_kinds") or [],
    }

async def plan_node(state: LearningState) -> LearningState:
    steps = [_norm_step(s) for s in (state.get("plan", {}).get("steps") or [])]
    if not steps:
        return {
            "plan": {"steps": []},
            "logs": ["plan: no baseline steps"],
        }

    provider = get_provider(state.get("model_id"))
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a planning agent. Update 'params' only; never remove steps. "
                    "Return JSON {steps:[{id,params}...]}. Keep ids intact."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"repo": state.get("repo"), "steps": steps}, separators=(",", ":")),
            },
        ]
        log.info("plan.enrich.request", extra={"steps": len(steps)})
        log.debug("plan.enrich.messages", extra={"system_head": _clip(messages[0]["content"]), "user_head": _clip(messages[1]["content"])})

        content = await provider.chat_json(messages)
        log.debug("plan.enrich.raw_content", extra={"len": len(content or ""), "head": _clip(content or "")})

        proposed = json.loads(content) if isinstance(content, str) else (content or {})
        param_overrides = {s["id"]: (s.get("params") or {}) for s in (proposed.get("steps") or []) if s.get("id")}
        applied = 0
        for s in steps:
            if s["id"] in param_overrides:
                s["params"] = {**s["params"], **param_overrides[s["id"]]}
                applied += 1
        log.info("plan.enrich.response", extra={"overrides_applied": applied})
        return {"plan": {"steps": steps}, "logs": ["plan: enriched by LLM"]}
    except Exception as e:
        log.info("plan: enrichment skipped (%s)", e)
        return {"plan": {"steps": steps}, "logs": [f"plan: enrichment skipped ({e})"]}
