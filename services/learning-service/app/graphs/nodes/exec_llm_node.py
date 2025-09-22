from __future__ import annotations

import json
from typing import Any, Dict, List

from app.llms.base import LLMRequest
from app.llms.registry import build_provider_from_llm_config
from app.clients.artifact_service import ArtifactServiceClient


async def _render_prompt(kind_id: str, version: str, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, str]:
    """
    Pulls the canonical prompt for a kind (if available) and renders a simple composite user prompt.
    If the registry lacks a prompt, falls back to a generic instruction with context.
    """
    async with ArtifactServiceClient() as arts:
        try:
            p = await arts.get_prompt(kind_id, version=version)
            system = (p or {}).get("system") or "You are a precise system that emits only valid JSON."
            user_tpl = (p or {}).get("user_template") or ""
        except Exception:
            # Fallback prompt
            system = "You are a precise system that emits only valid JSON."
            user_tpl = ""

    # Compose user message
    parts = [
        "Produce a valid JSON object for the requested artifact kind.",
        f"- Kind: `{kind_id}`",
        f"- Schema version: `{version}`",
        "",
        "### Inputs",
        json.dumps(inputs or {}, ensure_ascii=False, separators=(",", ":"), indent=2),
        "",
        "### Context (dependent artifacts)",
        json.dumps(context or {}, ensure_ascii=False, separators=(",", ":"), indent=2),
        "",
    ]
    if user_tpl:
        parts.append("### Additional Instructions")
        parts.append(user_tpl.strip())

    user = "\n".join(parts)
    return {"system": system, "user": user}


async def exec_llm_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    For each produced kind in the step, invoke the LLM once to obtain a single artifact JSON.
    (If a capability intends to produce multiple instances, that can be a later extension.)
    """
    idx = state.get("_step_index", 0)
    step = state["plan"]["steps"][idx]
    cap = step["capability_snapshot"]
    llm_cfg = (cap or {}).get("llm_config") or {}

    provider, req_defaults = build_provider_from_llm_config(llm_cfg)

    context = state.get("context") or {}
    inputs = state.get("inputs") or {}
    versions = state.get("kind_schema_version") or {}

    outputs: List[Dict[str, Any]] = []

    for kind_id in step.get("produces_kinds", []):
        version = versions.get(kind_id, "1.0.0")
        prompts = await _render_prompt(kind_id, version, context, inputs)
        req = LLMRequest(
            system_prompt=prompts["system"],
            user_prompt=prompts["user"],
            json_schema=None,  # Could fetch exact JSON schema from registry and pass it here later
            strict_json=True,
            **req_defaults,
        )
        obj = await provider.acomplete_json(req)
        # Coerce to item structure
        outputs.append({"kind_id": kind_id, "schema_version": version, "data": obj})

    state["last_output"] = outputs
    state["last_stats"] = {"produced_total": len(outputs)}
    return state
