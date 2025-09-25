# services/learning-service/app/graphs/nodes/exec_llm_node.py
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List

from app.llms.base import LLMRequest
from app.llms.registry import build_provider_from_llm_config
from app.clients.artifact_service import ArtifactServiceClient
from app.infra.rabbit import publish_step_event_v1
from app.models.events import LearningStepFailed, StepInfo


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
    Emits step.failed on exception (and re-raises).
    """
    idx = state.get("_step_index", 0)
    step = state["plan"]["steps"][idx]
    step_id = str(step.get("id") or step.get("step_id") or f"step{idx+1}")

    try:
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

    except Exception as e:
        # Publish step.failed (generic + specific) and re-raise
        rt = state.get("_step_runtime", {}).get(step_id) or {}
        started_at = rt.get("started_at") or datetime.utcnow()
        ended_at = datetime.utcnow()
        duration_s = (ended_at - started_at).total_seconds()

        payload = LearningStepFailed(
            run_id=state["run_id"],
            workspace_id=state["workspace_id"],
            playbook_id=state["playbook_id"],
            step=StepInfo(id=step_id, capability_id=step.get("capability_id"), name=step.get("name")),
            params=(step.get("params") or {}),
            produces_kinds=list(step.get("produces_kinds") or []),
            started_at=started_at,
            ended_at=ended_at,
            duration_s=duration_s,
            error=str(e),
        ).model_dump(mode="json")

        headers = {}
        if state.get("correlation_id"):
            headers["x-correlation-id"] = state["correlation_id"]
        await publish_step_event_v1(status="failed", payload=payload, headers=headers)

        # Update runtime status for idempotency
        state.setdefault("_step_runtime", {}).setdefault(step_id, {})["status"] = "failed"
        raise
