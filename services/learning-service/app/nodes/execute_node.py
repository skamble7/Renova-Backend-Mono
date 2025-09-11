# services/learning-service/app/nodes/execute_node.py
from __future__ import annotations
from typing import Dict, Any, List
from app.models.state import LearningState
from app.executor.runtime import make_runtime_config
from app.executor.tool_runner import run_tool
from app.agents.generic_kind_agent import GenericKindAgent

async def execute_node(state: LearningState) -> LearningState:
    ws = state.get("workspace_id")
    runtime = make_runtime_config(ws)
    steps: List[dict] = state.get("plan", {}).get("steps") or []
    produced_kinds: set[str] = set()
    generated: List[Dict[str, Any]] = []
    logs = state.setdefault("logs", [])

    tool_extras: Dict[str, Any] = {}

    for step in steps:
        sid = step.get("id") or "step"
        stype = (step.get("type") or "").lower()

        if stype == "tool_call":
            runtime_with_extras = {**runtime, "extras": tool_extras}
            tparams: Dict[str, Any] = dict(step.get("params") or {})

            # 🔧 Ensure the real repo values override any placeholders from the playbook
            if (step.get("tool_key") or "").strip() == "tool.github.fetch":
                repo_conf = state.get("repo") or {}
                # prefer explicit repo_url; fallback to url/repo keys if present
                url = repo_conf.get("repo_url") or repo_conf.get("url") or repo_conf.get("repo")
                if url:
                    tparams["repo_url"] = url
                    # keep backwards compat if runner expects 'repo'
                    tparams.setdefault("repo", url)
                tparams.setdefault("ref", repo_conf.get("ref", "main"))
                tparams.setdefault("depth", repo_conf.get("depth", 1))
                if "sparse_globs" not in tparams and repo_conf.get("sparse_globs") is not None:
                    tparams["sparse_globs"] = list(repo_conf["sparse_globs"])
                logs.append(f"{sid}: repo.override url={tparams.get('repo_url')} ref={tparams.get('ref')} depth={tparams.get('depth')}")

            arts, tlogs, extras = await run_tool(step.get("tool_key"), tparams, runtime_with_extras)
            logs += [f"{sid}: {m}" for m in tlogs]
            if extras:
                tool_extras.update(extras)
            if arts:
                generated.extend(arts)
                produced_kinds |= {a.get("kind") for a in arts if isinstance(a, dict)}
            continue

        if stype == "capability":
            agent = GenericKindAgent()
            for kind in (step.get("emits") or []):
                params = {"kind": kind, "name": kind.split(".")[-1].replace("_", " ").title()}
                ctx_env = {
                    "avc": (state.get("context") or {}).get("avc") or {},
                    "fss": (state.get("context") or {}).get("fss") or {},
                    "pss": (state.get("context") or {}).get("pss") or {},
                    "artifacts": {"items": list(generated)},
                }
                try:
                    result = await agent.run(ctx_env, params)
                    for p in (result.get("patches") or []):
                        if p.get("op") == "upsert" and p.get("path") == "/artifacts":
                            vals = p.get("value") or []
                            generated.extend(vals)
                            produced_kinds |= {a.get("kind") for a in vals if isinstance(a, dict)}
                    logs.append(f"{sid}:{kind}: generated")
                except Exception as e:
                    logs.append(f"{sid}:{kind}: ERROR {e}")
            continue

        logs.append(f"{sid}: skip unknown type '{stype}'")

    state["artifacts"] = generated
    state.setdefault("context", {})["tool_extras"] = tool_extras
    return state
