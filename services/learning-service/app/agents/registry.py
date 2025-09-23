# services/learning-service/app/agents/registry.py
from __future__ import annotations

from typing import Any, Dict, List, Literal
from pydantic import BaseModel, Field


class StepPlan(BaseModel):
    id: str
    name: str
    capability_id: str

    # Decides which executor node is used
    execution_mode: Literal["mcp", "llm"] = "llm"

    # Flattened for convenience during execution
    produces_kinds: List[str] = Field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    params: Dict[str, Any] = Field(default_factory=dict)

    # Keep the full snapshot handy (integration/llm_config/etc.)
    capability_snapshot: Dict[str, Any] = Field(default_factory=dict)


def build_step_plan(step: Dict[str, Any], cap_snapshot: Dict[str, Any]) -> StepPlan:
    """
    Normalize a playbook step + its capability snapshot into a StepPlan the graph uses.

    Robust execution mode selection:
      1) If step.execution_mode is explicitly set -> use it.
      2) Else if step.tool_calls present -> MCP.
      3) Else if capability.integration.tool_calls present -> MCP.
      4) Else if capability.integration present -> MCP (tools may be implicit).
      5) Else -> LLM (if llm_config present) or default to LLM.
    """
    cap = cap_snapshot or {}
    integration = (cap.get("integration") or {})
    llm_config = cap.get("llm_config") or None

    # Sources of tool calls (resolved packs may place these at step or capability)
    tool_calls_step = list(step.get("tool_calls") or [])
    tool_calls_cap = list((integration.get("tool_calls") or []))

    produces = list(step.get("produces_kinds") or cap.get("produces_kinds") or [])

    # Decide execution mode (no hard failure here; exec node will resolve/fetch integration if needed)
    explicit_mode = (step.get("execution_mode") or "").lower()
    if explicit_mode in ("mcp", "llm"):
        mode = explicit_mode
    elif tool_calls_step:
        mode = "mcp"
    elif tool_calls_cap:
        mode = "mcp"
    elif integration:
        mode = "mcp"
    else:
        mode = "llm" if llm_config else "llm"

    # Final tool_calls on the step plan (prefer step-level, then capability-level)
    tool_calls = tool_calls_step or tool_calls_cap

    return StepPlan(
        id=str(step.get("id") or step.get("step_id") or ""),
        name=str(step.get("name") or step.get("id") or step.get("step_id") or ""),
        capability_id=str(step.get("capability_id") or ""),
        execution_mode=mode,
        produces_kinds=produces,
        tool_calls=tool_calls,
        params=dict(step.get("params") or {}),
        capability_snapshot=cap_snapshot,
    )
