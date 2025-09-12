# services/learning-service/app/nodes/tool_exec_node.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple
import logging
from app.models.state import LearningState
from app.executor.runtime import make_runtime_config
from app.executor.tool_runner import run_tool

log = logging.getLogger("app.nodes.tool_exec")

# Minimal mapper for renova.cobol.quick (you can extend or load from registry later)
CAPABILITY_TO_TOOL = {
    "cap.source.fetch_from_github": "tool.github.fetch",
    "cap.cobol.parse_copybooks": "tool.copybook.to_xml",
    "cap.cobol.parse_programs": "tool.cobol.parse",
    "cap.cobol.derive_paragraph_flow": "tool.cobol.flow",
    # leave cap.code.* to the agent_synthesize_node
}

def _kinds(items: List[dict]) -> List[str]:
    return sorted({(a or {}).get("kind", "") for a in items if isinstance(a, dict)})

async def _exec_one(tool_key: str, params: Dict[str, Any], runtime: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
    try:
        return await run_tool(tool_key, params, runtime)
    except Exception as e:
        return [], [f"ERROR: {tool_key}: {e}"], {}

async def tool_exec_node(state: LearningState) -> LearningState:
    steps: List[dict] = list(state.get("plan", {}).get("steps") or [])
    if not steps:
        return {"artifacts": [], "context": {"tool_extras": {}, "tool_outputs": {}}, "logs": ["tool_exec: no steps"]}

    runtime = make_runtime_config(state.get("workspace_id") or "")
    produced: List[Dict[str, Any]] = []
    tool_extras: Dict[str, Any] = {}
    tool_outputs: Dict[str, Any] = {}
    logs: List[str] = []

    log.info("tool_exec.start", extra={"steps": len(steps)})

    for s in steps:
        sid = s.get("id") or "step"
        stype = (s.get("type") or "").lower()
        cap_id = s.get("capability_id")
        tool_key = s.get("tool_key")

        # Accept native tool_call OR mapped capability without an agent
        mapped_tool = CAPABILITY_TO_TOOL.get(cap_id or "", None)
        will_run = (stype == "tool_call" and tool_key) or mapped_tool

        if not will_run:
            continue

        tk = tool_key or mapped_tool
        params: Dict[str, Any] = dict(s.get("params") or {})

        # Enforce repo params for fetch
        if tk == "tool.github.fetch":
            repo_conf = state.get("repo") or {}
            # playbook value (if present) is fine; but runtime repo takes precedence
            params["repo_url"] = repo_conf.get("repo_url") or params.get("repo") or params.get("repo_url")
            params["ref"] = repo_conf.get("ref") or params.get("ref") or "main"
            if "sparse_globs" not in params and repo_conf.get("sparse_globs") is not None:
                params["sparse_globs"] = list(repo_conf["sparse_globs"])
            params["depth"] = repo_conf.get("depth", params.get("depth", 1))

        # Pass along any extras from prior tools
        runtime_with_extras = {**runtime, "extras": tool_extras}

        log.info("tool_exec.step.request", extra={"id": sid, "tool": tk})
        arts, tlogs, extras = await _exec_one(tk, params, runtime_with_extras)
        logs += [f"{sid}: {m}" for m in tlogs]

        if extras:
            tool_extras.update(extras)
        if arts:
            produced.extend(arts)

        # keep a compact envelope for downstream context
        tool_outputs[sid] = {
            "tool_key": tk,
            "emitted_kinds": _kinds(arts),
            "count": len(arts),
        }

        log.info("tool_exec.step", extra={"id": sid, "tool": tk, "emitted": _kinds(arts), "count": len(arts)})

    log.info("tool_exec.done", extra={"total_artifacts": len(produced), "kinds": _kinds(produced)})
    return {
        "artifacts": produced,
        "context": {"tool_extras": tool_extras, "tool_outputs": tool_outputs},
        "logs": logs or ["tool_exec: no tool steps executed"],
    }
