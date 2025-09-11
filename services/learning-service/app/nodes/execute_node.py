# services/learning-service/app/nodes/execute_node.py
from __future__ import annotations
from typing import Dict, Any, List, Set
import json, logging
from app.models.state import LearningState
from app.executor.runtime import make_runtime_config
from app.executor.tool_runner import run_tool
from app.agents.generic_kind_agent import GenericKindAgent

log = logging.getLogger("app.nodes.execute_node")


def _kinds(items: List[dict]) -> List[str]:
    return sorted({(a or {}).get("kind", "") for a in items if isinstance(a, dict)})


async def execute_node(state: LearningState) -> LearningState:
    # Build a runtime view from workspace id/name (do not echo it back)
    ws = state.get("workspace_id")
    runtime = make_runtime_config(ws)

    steps: List[dict] = state.get("plan", {}).get("steps") or []
    generated: List[Dict[str, Any]] = []
    new_logs: List[str] = []
    tool_extras: Dict[str, Any] = {}

    log.info("execute.start", extra={"steps": len(steps)})

    for step in steps:
        sid = step.get("id") or "step"
        stype = (step.get("type") or "").lower()
        emits = [e for e in (step.get("emits") or []) if isinstance(e, str)]
        requires = [r for r in (step.get("requires_kinds") or []) if isinstance(r, str)]

        if stype == "tool_call":
            runtime_with_extras = {**runtime, "extras": tool_extras}
            tparams: Dict[str, Any] = dict(step.get("params") or {})

            # Ensure actual repo values override any playbook placeholders
            if (step.get("tool_key") or "").strip() == "tool.github.fetch":
                repo_conf = state.get("repo") or {}
                url = repo_conf.get("repo_url") or repo_conf.get("url") or repo_conf.get("repo")
                if url:
                    tparams["repo_url"] = url
                    tparams.setdefault("repo", url)  # for runners that accept 'repo'
                tparams.setdefault("ref", repo_conf.get("ref", "main"))
                tparams.setdefault("depth", repo_conf.get("depth", 1))
                if "sparse_globs" not in tparams and repo_conf.get("sparse_globs") is not None:
                    tparams["sparse_globs"] = list(repo_conf["sparse_globs"])

            # Log the exact request body for this tool step
            try:
                log.info(
                    "execute.step.tool.request",
                    extra={
                        "id": sid,
                        "tool_key": step.get("tool_key"),
                        "requires": requires,
                        "emits": emits,
                        "params": tparams,
                    },
                )
            except Exception:
                pass

            arts, tlogs, extras = await run_tool(step.get("tool_key"), tparams, runtime_with_extras)
            new_logs += [f"{sid}: {m}" for m in tlogs]
            if extras:
                tool_extras.update(extras)
            if arts:
                generated.extend(arts)

            log.info(
                "execute.step.tool.result",
                extra={
                    "id": sid,
                    "kinds_emitted": _kinds(arts),
                    "kinds_total_so_far": _kinds(generated),
                    "count_emitted": len(arts),
                },
            )
            continue

        if stype == "capability":
            agent = GenericKindAgent()
            try:
                log.info(
                    "execute.step.capability.request",
                    extra={"id": sid, "capability_id": step.get("capability_id"), "emits": emits, "requires": requires},
                )
            except Exception:
                pass

            for kind in emits:
                params = {"kind": kind, "name": kind.split(".")[-1].replace("_", " ").title()}
                ctx_env = {
                    "avc": (state.get("context") or {}).get("avc") or {},
                    "fss": (state.get("context") or {}).get("fss") or {},
                    "pss": (state.get("context") or {}).get("pss") or {},
                    "artifacts": {"items": list(generated)},
                }
                try:
                    result = await agent.run(ctx_env, params)
                    emitted: List[dict] = []
                    for p in (result.get("patches") or []):
                        if p.get("op") == "upsert" and p.get("path") == "/artifacts":
                            vals = [v for v in (p.get("value") or []) if isinstance(v, dict)]
                            generated.extend(vals)
                            emitted.extend(vals)
                    new_logs.append(f"{sid}:{kind}: generated")
                    log.info(
                        "execute.step.capability.result",
                        extra={
                            "id": sid,
                            "kind": kind,
                            "count_emitted": len(emitted),
                            "kinds_total_so_far": _kinds(generated),
                        },
                    )
                except Exception as e:
                    new_logs.append(f"{sid}:{kind}: ERROR {e}")
                    log.warning("execute.step.capability.error", extra={"id": sid, "kind": kind, "error": str(e)})
            continue

        new_logs.append(f"{sid}: skip unknown type '{stype}'")
        log.info("execute.step.skip", extra={"id": sid, "type": stype})

    log.info("execute.done", extra={"total_artifacts": len(generated), "final_kinds": _kinds(generated)})
    return {
        "artifacts": generated,
        "context": {"tool_extras": tool_extras},
        "logs": new_logs,
    }
