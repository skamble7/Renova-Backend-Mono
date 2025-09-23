from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from app.integrations import IntegrationInvoker
from app.clients.capability_service import CapabilityServiceClient

logger = logging.getLogger("app.exec.mcp")

# Optional: persist per-tool audit entries
try:
    from app.db.runs import append_audit_entry  # type: ignore
except Exception:  # pragma: no cover
    append_audit_entry = None  # type: ignore


def _coerce_tool_output_to_items(result: Any) -> List[Dict[str, Any]]:
    """
    Canonicalize tool result into a list of items:
      { "artifacts": [ {kind_id, data, schema_version?}, ... ] }
      OR a single dict with kind/kind_id, OR a list of dicts.
    """
    if result is None:
        return []
    if isinstance(result, dict):
        if "artifacts" in result and isinstance(result["artifacts"], list):
            return [x for x in result["artifacts"] if isinstance(x, dict)]
        if "kind" in result or "kind_id" in result:
            return [result]
        return []
    if isinstance(result, list):
        return [x for x in result if isinstance(x, dict)]
    return []


def _flatten(prefix: str, obj: Any, out: Dict[str, Any]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten(f"{prefix}.{i}", v, out)
    else:
        out[prefix] = obj


_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _interpolate(value: Any, vars_map: Dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {k: _interpolate(v, vars_map) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v, vars_map) for v in value]
    if not isinstance(value, str):
        return value

    def repl(m: re.Match[str]) -> str:
        expr = m.group(1)
        if ":-" in expr:
            name, default = expr.split(":-", 1)
            name = name.strip()
        else:
            name, default = expr.strip(), ""
        raw = vars_map.get(name)
        return str(raw) if raw is not None else default

    return _VAR_RE.sub(repl, value)


def _inject_context_vars(vars_map: Dict[str, Any], context: Dict[str, Any]) -> None:
    """
    Derive convenient ${...} variables from context bundles.
    Example: repo snapshot -> repo.paths_root, repo.commit, repo.dest, etc.
    """
    if not isinstance(context, dict):
        return
    snapshots = context.get("cam.asset.repo_snapshot") or []
    if snapshots and isinstance(snapshots, list):
        # Prefer the most recent one (last)
        snap = snapshots[-1]
        data = snap.get("data") if isinstance(snap, dict) else None
        if isinstance(data, dict):
            if "paths_root" in data:
                vars_map.setdefault("repo.paths_root", data["paths_root"])
            if "dest" in data:
                vars_map.setdefault("repo.dest", data["dest"])
            if "commit" in data:
                vars_map.setdefault("repo.commit", data["commit"])


async def _resolve_integration_snapshot(
    *,
    step_integration: Dict[str, Any],
    cap_integration: Dict[str, Any],
    capability_id: Optional[str],
    correlation_id: Optional[str],
) -> Dict[str, Any]:
    """
    Resolve to a concrete integration snapshot, with these fallbacks:
      1) step.integration.integration_snapshot
      2) cap.integration.integration_snapshot
      3) step.integration.integration_ref -> GET /integration/{id}
      4) cap.integration.integration_ref -> GET /integration/{id}
      5) capability_id -> GET /capability/{id} -> integration_ref -> GET /integration/{id}
    """
    integ = dict(step_integration or {}) or dict(cap_integration or {})

    # 1/2) snapshot present?
    snap = integ.get("integration_snapshot") or {}
    if snap:
        return snap

    # 3/4) have a ref directly on step/cap?
    ref = (
        integ.get("integration_ref")
        or (step_integration or {}).get("integration_ref")
        or (cap_integration or {}).get("integration_ref")
    )
    if ref:
        async with CapabilityServiceClient() as caps:
            resolved = await caps.get_integration(str(ref), correlation_id=correlation_id)
        if resolved:
            return resolved

    # 5) fetch capability, then resolve its ref
    if capability_id:
        async with CapabilityServiceClient() as caps:
            cap = await caps.get_capability(capability_id, correlation_id=correlation_id)
        integ2 = (cap or {}).get("integration") or {}
        snap2 = integ2.get("integration_snapshot") or {}
        if snap2:
            return snap2
        ref2 = integ2.get("integration_ref")
        if ref2:
            async with CapabilityServiceClient() as caps:
                resolved = await caps.get_integration(str(ref2), correlation_id=correlation_id)
            if resolved:
                return resolved

    raise ValueError("Capability step/capability snapshot missing integration_ref/integration_snapshot")


def _args_preview(args: Dict[str, Any]) -> Dict[str, Any]:
    keys = {"url", "branch", "revision", "dest", "root", "paths", "dialect"}
    preview: Dict[str, Any] = {}
    for k, v in args.items():
        if k in keys or isinstance(v, (str, int, float, bool)):
            preview[k] = v
    return preview


async def exec_mcp_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute MCP tools for the current step; accumulate items in state['last_output'].
    Adds INFO logs and per-tool audit rows. Robustly resolves integration snapshots.
    """
    idx = state.get("_step_index", 0)
    step = (state["plan"]["steps"])[idx]
    step_id = step.get("id") or f"step{idx+1}"

    cap = step.get("capability_snapshot") or {}
    cap_integration = (cap or {}).get("integration") or {}
    step_integration = step.get("integration") or {}  # some resolved views include this
    capability_id = step.get("capability_id")

    correlation_id = state.get("correlation_id")

    # Resolve the actual transport snapshot (with safe fallbacks)
    snapshot = await _resolve_integration_snapshot(
        step_integration=step_integration,
        cap_integration=cap_integration,
        capability_id=capability_id,
        correlation_id=correlation_id,
    )

    # Runtime vars for interpolation in transport + args
    workspace_folder = (
        (state.get("options") or {}).get("workspace_folder")
        or os.getenv("WORKSPACE_FOLDER")
        or os.getenv("workspaceFolder")
        or f"/workspaces/{state['workspace_id']}"
    )
    runtime_vars = {"workspaceFolder": workspace_folder}

    # Build a variable map for ${...}
    inputs = state.get("inputs") or {}
    vars_map: Dict[str, Any] = dict(runtime_vars)
    _flatten("", inputs, vars_map)

    # Derive handy vars from context (e.g., repo.paths_root)
    _inject_context_vars(vars_map, state.get("context") or {})

    # Convenience aliases from inputs.repos[0]
    repos = (inputs.get("repos") or [])
    if repos and isinstance(repos, list) and isinstance(repos[0], dict):
        vars_map.setdefault("git.url", repos[0].get("url"))
        vars_map.setdefault("git.branch", repos[0].get("revision") or repos[0].get("branch"))

    # Log the chosen transport
    t = snapshot.get("transport") or {}
    logger.info(
        "MCP(exec): step=%s transport.kind=%s command=%s base_url=%s cwd=%s",
        step_id, (t.get("kind") or "").lower(), t.get("command"), t.get("base_url"), t.get("cwd"),
    )

    results: List[Dict[str, Any]] = []
    state.setdefault("_audit_calls", [])

    async with IntegrationInvoker(snapshot, runtime_vars=runtime_vars) as inv:
        for spec in step.get("tool_calls", []):
            tool = spec.get("tool")
            timeout_sec = spec.get("timeout_sec")
            retries = int(spec.get("retries", 0))

            # Start from spec.args (if present), then merge step.params
            args: Dict[str, Any] = dict(spec.get("args") or {})
            args.update(dict(step.get("params") or {}))

            args.setdefault("inputs", inputs)
            args.setdefault("context", state.get("context"))

            args = _interpolate(args, vars_map)

            logger.info(
                "MCP(tool): step=%s tool=%s retries=%s timeout=%s args=%s",
                step_id, tool, retries, timeout_sec, _args_preview(args),
            )

            t0 = time.perf_counter()
            error: Optional[str] = None
            produced = 0
            try:
                out = await inv.call_tool(tool, args, timeout_sec=timeout_sec, retries=retries, correlation_id=correlation_id)
                items = _coerce_tool_output_to_items(out)
                produced = len(items)
                results.extend(items)
            except Exception as e:  # pragma: no cover
                error = str(e)
                logger.exception("MCP(tool) FAILED: step=%s tool=%s error=%s", step_id, tool, error)

            dur_ms = int((time.perf_counter() - t0) * 1000)
            call_audit = {"tool": tool, "args": _args_preview(args), "duration_ms": dur_ms, "produced_count": produced, "error": error}
            state["_audit_calls"].append(call_audit)

            if append_audit_entry:
                try:
                    await append_audit_entry(state["run_id"], {
                        "step_id": step_id,
                        "capability_id": step.get("capability_id"),
                        "mode": "mcp",
                        "inputs_preview": {"inputs": {}, "context_keys": list((state.get("context") or {}).keys())},
                        "calls": [call_audit],
                    })
                except Exception:
                    pass

    state["last_output"] = results
    state["last_stats"] = {"produced_total": len(results)}
    return state
