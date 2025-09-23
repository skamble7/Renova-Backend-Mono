# services/learning-service/app/graphs/nodes/exec_mcp_node.py
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


def _maybe_unwrap_result(obj: Any) -> Any:
    if isinstance(obj, dict) and "result" in obj and isinstance(obj["result"], (dict, list)):
        return obj["result"]
    return obj


def _collect_top_keys(obj: Any) -> List[str]:
    if isinstance(obj, dict):
        return list(obj.keys())[:20]
    return ["<non-dict>"]


def _parse_maybe_json_string(s: Any) -> Any:
    if isinstance(s, str):
        try:
            return json.loads(s)
        except Exception:
            return None
    return None


def _extract_artifacts_from_container(container: Any, out: List[Dict[str, Any]]) -> None:
    """
    Pull artifacts from a single container object (dict).
    Supported shapes inside 'container':
      - container["structuredContent"]["artifacts"]
      - container["structuredContent"]["body"]["artifacts"]
      - container["structured_content"]["artifacts"]  (snake_case)
      - container["artifacts"]
      - container["items"] / ["outputs"] / ["records"] / ["documents"] (each element may be an artifact)
      - container is actually {"artifacts":[...]} or {"body":{"artifacts":[...]}}
      - container["content"] entries:
            {type:"text", text:"<json>"} OR {type:"json", json:<obj>} OR a raw JSON string
    """
    if not isinstance(container, dict):
        return

    # canonical and snake_case
    sc = container.get("structuredContent") or container.get("structured_content")
    if isinstance(sc, dict):
        ra = sc.get("artifacts")
        if isinstance(ra, list):
            out.extend([a for a in ra if isinstance(a, dict)])
        body = sc.get("body")
        if isinstance(body, dict) and isinstance(body.get("artifacts"), list):
            out.extend([a for a in body["artifacts"] if isinstance(a, dict)])

    # direct artifacts on container
    ra2 = container.get("artifacts")
    if isinstance(ra2, list):
        out.extend([a for a in ra2 if isinstance(a, dict)])

    # items-like holders frequently used by tools
    for k in ("items", "outputs", "records", "documents"):
        seq = container.get(k)
        if isinstance(seq, list):
            out.extend([a for a in seq if isinstance(a, dict)])

    # container may itself be {"body":{"artifacts":[...]}}
    if isinstance(container.get("body"), dict) and isinstance(container["body"].get("artifacts"), list):
        out.extend([a for a in container["body"]["artifacts"] if isinstance(a, dict)])

    # content: text/json
    content = container.get("content")
    if isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                # Raw string content, try parse
                parsed = _parse_maybe_json_string(c)
                if isinstance(parsed, dict):
                    _extract_artifacts_from_container(parsed, out)
                elif isinstance(parsed, list):
                    for el in parsed:
                        if isinstance(el, dict):
                            _extract_artifacts_from_container(el, out)
                continue

            ctype = (c.get("type") or "").lower()
            if ctype == "text" and isinstance(c.get("text"), str):
                parsed = _parse_maybe_json_string(c["text"])
                if isinstance(parsed, dict):
                    _extract_artifacts_from_container(_maybe_unwrap_result(parsed), out)
                elif isinstance(parsed, list):
                    for el in parsed:
                        if isinstance(el, dict):
                            _extract_artifacts_from_container(el, out)
            elif ctype == "json":
                payload = c.get("json")
                if isinstance(payload, (dict, list)):
                    payload = _maybe_unwrap_result(payload)
                    if isinstance(payload, dict):
                        _extract_artifacts_from_container(payload, out)
                    elif isinstance(payload, list):
                        for el in payload:
                            if isinstance(el, dict):
                                _extract_artifacts_from_container(el, out)


def _extract_artifacts(result: Any) -> List[Dict[str, Any]]:
    """
    Collect artifact dicts from many MCP result shapes.
    Also supports:
      - top-level list of artifact-like dicts
      - {"result":[...]} wrapping
    """
    arts: List[Dict[str, Any]] = []

    # unwrap one layer of {"result": ...} if present
    result = _maybe_unwrap_result(result)

    # top-level list
    if isinstance(result, list):
        for el in result:
            if isinstance(el, dict):
                # Either an artifact object or a container of artifacts
                # Quick check: if it looks like an artifact, collect directly.
                if any(k in el for k in ("kind", "kind_id", "kindId")):
                    arts.append(el)
                else:
                    _extract_artifacts_from_container(el, arts)
        return arts

    # dict container
    if isinstance(result, dict):
        _extract_artifacts_from_container(result, arts)

    return arts


def _normalize_artifact(a: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize an artifact envelope to engine-canon.
    Accept synonyms: kindId, schemaVersion, payload.
    """
    kind_id = a.get("kind_id") or a.get("kindId") or a.get("kind")
    version = a.get("schema_version") or a.get("schemaVersion") or a.get("version") or a.get("ver")
    # Payload keys we accept in priority order
    if "data" in a and a.get("data") is not None:
        data = a.get("data")
    elif "payload" in a and a.get("payload") is not None:
        data = a.get("payload")
    else:
        data = a.get("body") or {}

    return {
        "kind_id": kind_id,
        "version": version,
        "schema_version": version,
        "data": data,
        # Back-compat mirrors
        "kind": kind_id,
        "body": data,
    }


def _normalize_artifacts(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_normalize_artifact(x) for x in raw if isinstance(x, dict)]


def _dedupe_artifacts(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    keys = {"url", "branch", "revision", "dest", "root", "paths", "dialect", "allow_missing_kinds"}
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


def _find_tool_schema(snapshot: dict, tool_name: str) -> Optional[dict]:
    for t in (snapshot.get("tools") or []):
        if t.get("name") == tool_name:
            return t.get("inputSchema") or t.get("input_schema") or {}
    return None


def _filter_args_by_schema(schema: dict, args: dict) -> dict:
    if not isinstance(schema, dict):
        return dict(args)
    props = schema.get("properties")
    if not isinstance(props, dict) or not props:
        return dict(args)
    allowed = set(props.keys())
    return {k: v for k, v in args.items() if k in allowed}


async def exec_mcp_node(state: Dict[str, Any]) -> Dict[str, Any]:
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

    workspace_folder = (
        (state.get("options") or {}).get("workspace_folder")
        or os.getenv("WORKSPACE_FOLDER")
        or os.getenv("workspaceFolder")
        or f"/workspaces/{state['workspace_id']}"
    )
    runtime_vars = {"workspaceFolder": workspace_folder}

    inputs = state.get("inputs") or {}
    base_vars: Dict[str, Any] = dict(runtime_vars)
    _flatten("", inputs, base_vars)

    hints = state.get("_hints") or {}
    if isinstance(hints, dict):
        base_vars.update(hints)

    repos = (inputs.get("repos") or [])
    if repos and isinstance(repos, list) and isinstance(repos[0], dict):
        base_vars.setdefault("git.url", repos[0].get("url"))
        base_vars.setdefault("git.branch", repos[0].get("revision") or repos[0].get("branch"))

    ctx = state.setdefault("context", {})

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

            vars_map: Dict[str, Any] = dict(base_vars)
            _inject_context_vars(vars_map, ctx)

            raw_args: Dict[str, Any] = dict(spec.get("args") or {})
            raw_args.update(dict(step.get("params") or {}))
            interpolated = _interpolate(raw_args, vars_map)

            tool_schema = _find_tool_schema(snapshot, tool)
            args = _filter_args_by_schema(tool_schema or {}, interpolated)

            logger.info(
                "MCP(tool): step=%s tool=%s retries=%s timeout=%s args=%s",
                step_id, tool, retries, timeout_sec, _args_preview(args),
            )

            t0 = time.perf_counter()
            error: Optional[str] = None
            produced = 0
            kinds: List[str] = []
            zero_warned = False

            try:
                out = await inv.call_tool(tool, args, timeout_sec=timeout_sec, retries=retries, correlation_id=correlation_id)

                logger.info("MCP(raw): step=%s tool=%s out=%s", step_id, tool, _short_json(out))

                maybe = _maybe_unwrap_result(out)
                if isinstance(maybe, dict) and maybe.get("isError") is True:
                    raise RuntimeError(_mcp_error_text(maybe))

                raw_items = _extract_artifacts(out)
                if not raw_items and isinstance(maybe, dict) and not zero_warned:
                    zero_warned = True
                    logger.warning(
                        "MCP(extract): step=%s tool=%s produced 0 artifacts; top-level keys=%s",
                        step_id, tool, _collect_top_keys(maybe),
                    )

                items = _normalize_artifacts(raw_items)
                items = _dedupe_artifacts(items)

                produced = len(items)
                kinds = [i.get("kind_id") or "" for i in items]
                logger.info("MCP(result): step=%s tool=%s produced=%d kinds=%s", step_id, tool, produced, kinds)

                _merge_items_into_context(ctx, items)
                _update_repo_hints(state, items)
                results.extend(items)

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
                raise RuntimeError(error)

    state["last_output"] = results
    state["last_stats"] = {"produced_total": len(results)}
    state["context"] = ctx
    return state
