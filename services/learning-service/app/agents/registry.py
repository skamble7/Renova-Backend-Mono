from __future__ import annotations

from typing import Any, Dict, List, Literal

from app.agents.spi import StepPlan


def _execution_mode(cap_snap: Dict[str, Any]) -> Literal["mcp", "llm"]:
    """
    Decide whether a capability snapshot runs via MCP or LLM.
    """
    integration = (cap_snap or {}).get("integration") or {}
    llm_cfg = (cap_snap or {}).get("llm_config") or {}
    if integration:
        return "mcp"
    if llm_cfg:
        return "llm"
    # Fallback: if neither declared, default to LLM to allow reasoning
    return "llm"


def _produces_kinds(cap_snap: Dict[str, Any]) -> List[str]:
    return list((cap_snap or {}).get("produces_kinds") or [])


def _tool_calls(cap_snap: Dict[str, Any]) -> List[Dict[str, Any]]:
    integration = (cap_snap or {}).get("integration") or {}
    return list(integration.get("tool_calls") or [])


def build_step_plan(step_def: Dict[str, Any], cap_snap: Dict[str, Any]) -> StepPlan:
    """
    Create a normalized StepPlan consumers can rely on.
    `step_def` is the playbook step from the pack (id, name, capability_id, params?).
    `cap_snap` is the matching capability snapshot included in the resolved pack.
    """
    mode = _execution_mode(cap_snap)
    kinds = _produces_kinds(cap_snap)
    tool_calls = _tool_calls(cap_snap) if mode == "mcp" else []
    return StepPlan(
        step_id=str(step_def.get("id")),
        name=str(step_def.get("name") or step_def.get("id")),
        capability_id=str(step_def.get("capability_id")),
        mode=mode,
        produces_kinds=kinds,
        tool_calls=tool_calls,
        capability_snapshot=cap_snap,
    )
