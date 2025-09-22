from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.integrations import IntegrationInvoker


def _coerce_tool_output_to_items(result: Any) -> List[Dict[str, Any]]:
    """
    Flexible coercion of tool output to a canonical list of {kind_id, data} items.
    Expected happy path:
      { "artifacts": [ { "kind_id": "cam.*", "data": {...}, "schema_version":"1.0.0" }, ... ] }
    Also accept a raw list or single object.
    """
    if result is None:
        return []
    if isinstance(result, dict):
        if "artifacts" in result and isinstance(result["artifacts"], list):
            return [x for x in result["artifacts"] if isinstance(x, dict)]
        # treat dict as single item if it has 'kind' or 'kind_id'
        if "kind" in result or "kind_id" in result:
            return [result]
        return []
    if isinstance(result, list):
        return [x for x in result if isinstance(x, dict)]
    return []


async def exec_mcp_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute MCP tools for the current step.
    Accumulates raw outputs into state['last_output'] as a flat list of items.
    """
    idx = state.get("_step_index", 0)
    step = state["plan"]["steps"][idx]
    cap = step["capability_snapshot"]
    integration = (cap or {}).get("integration") or {}
    snapshot = integration.get("integration_snapshot") or {}

    correlation_id = state.get("correlation_id")

    results: List[Dict[str, Any]] = []
    async with IntegrationInvoker(snapshot) as inv:
        for spec in step.get("tool_calls", []):
            tool = spec.get("tool")
            timeout_sec = spec.get("timeout_sec")
            retries = int(spec.get("retries", 0))
            args = dict(spec.get("args") or {})  # step-level default args if any
            # Enrich with run-level inputs if needed (e.g., repos)
            args.setdefault("inputs", state.get("inputs"))
            args.setdefault("context", state.get("context"))

            out = await inv.call_tool(
                tool,
                args,
                timeout_sec=timeout_sec,
                retries=retries,
                correlation_id=correlation_id,
            )
            results.extend(_coerce_tool_output_to_items(out))

    state["last_output"] = results
    # Minimal stats payload
    state["last_stats"] = {"produced_total": len(results)}
    return state
