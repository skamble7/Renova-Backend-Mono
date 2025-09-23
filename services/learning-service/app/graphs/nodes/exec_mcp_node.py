from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from app.integrations import IntegrationInvoker
from app.clients.capability_service import CapabilityServiceClient

logger = logging.getLogger("app.exec.mcp")


# Optional: persist per-tool audit entries
try:
    from app.db.runs import append_audit_entry  # type: ignore
except Exception:  # pragma: no cover
    append_audit_entry = None  # type: ignore


def _short_json(data: Any, *, max_len: int = 4000) -> str:
    try:
        s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        s = repr(data)
    return s if len(s) <= max_len else s[: max_len - 20] + "... <truncated>"


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
    Populate handy ${repo.*} vars from any repo snapshot entries we’ve stashed in context.
    Accept payloads under either 'data' or 'body'.
    """
    if not isinstance(context, dict):
        return
    snaps = context.get("cam.asset.repo_snapshot") or []
    if isinstance(snaps, list) and snaps:
        latest = snaps[-1]
        payload = None
        if isinstance(latest, dict):
            payload = latest.get("data") or latest.get("body") or latest
        if isinstance(payload, dict):
            if "paths_root" in payload:
                vars_map.setdefault("repo.paths_root", payload["paths_root"])
            if "commit" in payload:
                vars_map.setdefault("repo.commit", payload["commit"])
            if "dest" in payload:
                vars_map.setdefault("repo.dest", payload["dest"])


def _extract_artifacts(result: Any) -> List[Dict[str, Any]]:
    """
    Find artifact envelopes in common MCP shapes:
      - result["structuredContent"]["artifacts"]
      - result["artifacts"]
      - JSON string inside result["content"][...]["text"] with {"artifacts":[...]}
    Returns the *raw* artifact dicts (no key normalization yet).
    """
    arts: List[Dict[str, Any]] = []

    if isinstance(result, dict):
        sc = result.get("structuredContent")
        if isinstance(sc, dict):
            ra = sc.get("artifacts")
            if isinstance(ra, list):
                arts.extend([a for a in ra if isinstance(a, dict)])

        ra2 = result.get("artifacts")
        if isinstance(ra2, list):
            arts.extend([a for a in ra2 if isinstance(a, dict)])

        content = result.get("content")
        if isinstance(content, list):
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
                    txt = c["text"]
                    try:
                        maybe = json.loads(txt)
                        if isinstance(maybe, dict) and isinstance(maybe.get("artifacts"), list):
                            arts.extend([a for a in maybe["artifacts"] if isinstance(a, dict)])
                    except Exception:
                        pass

    return arts


def _normalize_artifact(a: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize an artifact envelope to engine-canon:
      { "kind_id": str, "version": str|None, "data": object }
    Also include 'kind' and 'body' for compatibility with other code paths.
    """
    kind_id = a.get("kind_id") or a.get("kind")
    version = a.get("version") or a.get("schema_version") or a.get("ver")
    data = a.get("data") or a.get("body") or {}
    norm = {
        "kind_id": kind_id,
        "version": version,
        "data": data,
        # Back-compat mirrors
        "kind": kind_id,
        "body": data,
    }
    return norm


def _normalize_artifacts(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_normalize_artifact(x) for x in raw if isinstance(x, dict)]


def _dedupe_artifacts(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    De-duplicate by (kind_id, version, data JSON) to avoid double counting the same artifact
    when it appears in both structuredContent and content.text JSON.
    """
    seen: set[Tuple[str, str, str]] = set()
    uniq: List[Dict[str, Any]] = []
    for it in items:
        k = (it.get("kind_id") or "", it.get("version") or "", json.dumps(it.get("data"), sort_keys=True))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)
    return uniq


def _merge_items_into_context(ctx: Dict[str, Any], items: List[Dict[str, Any]]) -> int:
    """
    Merge normalized artifacts into context as:
      context[kind_id] += [{ "data": <payload> }]
    """
    if not isinstance(ctx, dict):
        return 0
    merged = 0
    for it in items:
        kind_id = it.get("kind_id") or it.get("kind")
        payload = it.get("data") or it.get("body")
        if not kind_id or payload is None:
            continue
        ctx.setdefault(kind_id, []).append({"data": payload})
        merged += 1
    return merged


def _update_repo_hints(state: Dict[str, Any], items: List[Dict[str, Any]]) -> None:
    """
    Persist handy repo hints across steps so downstream tools can default args.
    """
    hints = state.setdefault("_hints", {})
    for it in items:
        if (it.get("kind_id") or it.get("kind")) == "cam.asset.repo_snapshot":
            payload = it.get("data") or it.get("body") or {}
            if isinstance(payload, dict):
                if isinstance(payload.get("paths_root"), str) and payload["paths_root"].strip():
                    hints["repo.paths_root"] = payload["paths_root"]
                if isinstance(payload.get("commit"), str):
                    hints["repo.commit"] = payload["commit"]
                if isinstance(payload.get("branch"), str):
                    hints["git.branch"] = payload["branch"]
                if isinstance(payload.get("repo"), str):
                    hints["git.url"] = payload["repo"]


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
      3) step/cap integration_ref -> GET /integration/{id}
      4) capability_id -> GET /capability/{id} -> integration_ref -> GET /integration/{id}
    """
    integ = dict(step_integration or {}) or dict(cap_integration or {})

    snap = integ.get("integration_snapshot") or {}
    if snap:
        return snap

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


def _mcp_error_text(out: Dict[str, Any]) -> str:
    if not isinstance(out, dict):
        return "MCP returned an error"
    content = out.get("content")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str):
                return c["text"]
    for key in ("error", "message", "detail"):
        val = out.get(key)
        if isinstance(val, str) and val:
            return val
    return "MCP returned an error"


def _latest_repo_root_from_context(ctx: Dict[str, Any]) -> Optional[str]:
    lst = (ctx or {}).get("cam.asset.repo_snapshot") or []
    if not isinstance(lst, list) or not lst:
        return None
    last = lst[-1]
    if isinstance(last, dict):
        b = last.get("data") or last.get("body") or last
        if isinstance(b, dict):
            root = b.get("paths_root")
            if isinstance(root, str) and root.strip():
                return root
    return None


async def exec_mcp_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute MCP tools for the current step; normalize artifacts to {kind_id,version,data};
    log raw returns + kinds; merge into context; persist repo hints; default parse_tree.root.
    """
    idx = state.get("_step_index", 0)
    step = (state["plan"]["steps"])[idx]
    step_id = step.get("id") or f"step{idx+1}"

    cap = step.get("capability_snapshot") or {}
    cap_integration = (cap or {}).get("integration") or {}
    step_integration = step.get("integration") or {}
    capability_id = step.get("capability_id")
    correlation_id = state.get("correlation_id")

    snapshot = await _resolve_integration_snapshot(
        step_integration=step_integration,
        cap_integration=cap_integration,
        capability_id=capability_id,
        correlation_id=correlation_id,
    )

    # Runtime vars baseline
    workspace_folder = (
        (state.get("options") or {}).get("workspace_folder")
        or os.getenv("WORKSPACE_FOLDER")
        or os.getenv("workspaceFolder")
        or f"/workspaces/{state['workspace_id']}"
    )
    runtime_vars = {"workspaceFolder": workspace_folder}

    # Inputs → flat vars
    inputs = state.get("inputs") or {}
    base_vars: Dict[str, Any] = dict(runtime_vars)
    _flatten("", inputs, base_vars)

    # Carry across persistent repo hints from previous steps
    hints = state.get("_hints") or {}
    if isinstance(hints, dict):
        base_vars.update(hints)

    # Convenience aliases from inputs.repos[0]
    repos = (inputs.get("repos") or [])
    if repos and isinstance(repos, list) and isinstance(repos[0], dict):
        base_vars.setdefault("git.url", repos[0].get("url"))
        base_vars.setdefault("git.branch", repos[0].get("revision") or repos[0].get("branch"))

    # Ensure context bucket exists
    ctx = state.setdefault("context", {})

    # Transport log
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

            # Build vars for this call (include latest context-derived vars)
            vars_map: Dict[str, Any] = dict(base_vars)
            _inject_context_vars(vars_map, ctx)

            # Build and interpolate args
            args: Dict[str, Any] = dict(spec.get("args") or {})
            args.update(dict(step.get("params") or {}))
            # NOTE: Some MCP tools validate strictly; avoid sending extra keys they don't expect.

            args = _interpolate(args, vars_map)

            # Special default: if parse_tree.root is empty, use latest repo snapshot
            if tool == "parse_tree":
                need_root = not isinstance(args.get("root"), str) or not args.get("root", "").strip()
                if need_root:
                    auto_root = (
                        _latest_repo_root_from_context(ctx)
                        or (state.get("_hints") or {}).get("repo.paths_root")
                        or vars_map.get("repo.paths_root")
                    )
                    if isinstance(auto_root, str) and auto_root.strip():
                        args["root"] = auto_root
                        logger.info("MCP(args): step=%s tool=%s defaulted root=%s", step_id, tool, auto_root)

            logger.info(
                "MCP(tool): step=%s tool=%s retries=%s timeout=%s args=%s",
                step_id, tool, retries, timeout_sec, _args_preview(args),
            )

            t0 = time.perf_counter()
            error: Optional[str] = None
            produced = 0
            kinds: List[str] = []

            try:
                out = await inv.call_tool(tool, args, timeout_sec=timeout_sec, retries=retries, correlation_id=correlation_id)

                # Log raw server return
                logger.info("MCP(raw): step=%s tool=%s out=%s", step_id, tool, _short_json(out))

                if isinstance(out, dict) and out.get("isError") is True:
                    raise RuntimeError(_mcp_error_text(out))

                raw_items = _extract_artifacts(out)
                items = _normalize_artifacts(raw_items)
                items = _dedupe_artifacts(items)

                produced = len(items)
                kinds = [i.get("kind_id") or "" for i in items]
                logger.info("MCP(result): step=%s tool=%s produced=%d kinds=%s", step_id, tool, produced, kinds)

                # Merge into context for downstream steps
                _merge_items_into_context(ctx, items)
                # Persist repo hints across steps
                _update_repo_hints(state, items)
                results.extend(items)

                # Gate: clone must produce repo snapshot before any downstream step that needs root
                if tool == "clone_repo" and "cam.asset.repo_snapshot" not in kinds:
                    raise RuntimeError("clone_repo did not return cam.asset.repo_snapshot; halting pipeline")

                # After successful call, refresh base vars from updated context + hints
                base_vars = dict(runtime_vars)
                _flatten("", inputs, base_vars)
                if isinstance(state.get("_hints"), dict):
                    base_vars.update(state["_hints"])  # type: ignore[index]
                _inject_context_vars(base_vars, ctx)

            except Exception as e:  # pragma: no cover
                error = str(e)
                logger.exception("MCP(tool) FAILED: step=%s tool=%s error=%s", step_id, tool, error)

            dur_ms = int((time.perf_counter() - t0) * 1000)
            call_audit = {
                "tool": tool,
                "args": _args_preview(args),
                "duration_ms": dur_ms,
                "produced_count": produced,
                "error": error,
            }
            state["_audit_calls"].append(call_audit)

            if append_audit_entry:
                try:
                    await append_audit_entry(
                        state["run_id"],
                        {
                            "step_id": step_id,
                            "capability_id": step.get("capability_id"),
                            "mode": "mcp",
                            "inputs_preview": {"inputs": {}, "context_keys": list((ctx or {}).keys())},
                            "calls": [call_audit],
                        },
                    )
                except Exception:
                    pass

            if error:
                # Stop this node on failure so the graph can report the error clearly
                raise RuntimeError(error)

    state["last_output"] = results  # normalized artifacts with kind_id/version/data (+ kind/body)
    state["last_stats"] = {"produced_total": len(results)}
    state["context"] = ctx
    return state
