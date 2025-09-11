# services/learning-service/app/nodes/plan_node.py
from __future__ import annotations
from typing import Dict, Any, List
from app.models.state import LearningState
from app.llms.registry import get_provider
import json

def _norm_step(s: dict) -> dict:
    # keep ids and tool_key/capability_id
    return {"id": s.get("id"), "type": s.get("type"), "tool_key": s.get("tool_key"), "capability_id": s.get("capability_id"),
            "params": s.get("params") or {}, "emits": s.get("emits") or [], "requires_kinds": s.get("requires_kinds") or []}

async def plan_node(state: LearningState) -> LearningState:
    steps = [_norm_step(s) for s in (state.get("plan", {}).get("steps") or [])]
    if not steps:
        state["plan"] = {"steps": []}
        state.setdefault("logs", []).append("plan: no baseline steps")
        return state

    # Optional enrichment: allow LLM to tweak params (e.g., sparse globs), keep order & ids
    provider = get_provider(state.get("model_id"))
    try:
        messages = [
            {"role": "system", "content": "You are a planning agent. Update 'params' only; never remove steps. Return JSON {steps:[{id,params}...]}. Keep ids intact."},
            {"role": "user", "content": json.dumps({"repo": state.get("repo"), "steps": steps}, separators=(",", ":"))}
        ]
        content = await provider.chat_json(messages)
        proposed = json.loads(content) if isinstance(content, str) else content
        param_overrides = {s["id"]: (s.get("params") or {}) for s in (proposed.get("steps") or []) if s.get("id")}
        for s in steps:
            if s["id"] in param_overrides:
                s["params"] = {**s["params"], **param_overrides[s["id"]]}
        state["plan"] = {"steps": steps}
        state.setdefault("logs", []).append("plan: enriched by LLM")
    except Exception as e:
        state["plan"] = {"steps": steps}
        state.setdefault("logs", []).append(f"plan: enrichment skipped ({e})")
    return state
