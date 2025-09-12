# services/learning-service/app/nodes/agent_synthesize_node.py
from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.models.state import LearningState
from app.agents.generic_kind_agent import GenericKindAgent

logger = logging.getLogger("app.nodes.agent_synthesize")

_MAX_PREVIEW = 80
_MAX_VAL_CHARS = 800


def _trim_val(v: Any, max_chars: int = _MAX_VAL_CHARS) -> Any:
    try:
        import json as _json
        if isinstance(v, (dict, list)):
            s = _json.dumps(v, ensure_ascii=False)
        else:
            s = str(v)
        if len(s) > max_chars:
            s = s[:max_chars] + f"...(+{len(s)-max_chars} chars)"
        return s
    except Exception:
        try:
            s = str(v)
            if len(s) > max_chars:
                s = s[:max_chars] + f"...(+{len(s)-max_chars} chars)"
            return s
        except Exception:
            return "<unloggable>"


def _preview(items: List[dict], n: int = _MAX_PREVIEW) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for a in (items or [])[:n]:
        if not isinstance(a, dict):
            continue
        out.append({"kind": a.get("kind"), "name": a.get("name"), "data_preview": _trim_val(a.get("data"))})
    return out


def _kinds(items: List[dict]) -> List[str]:
    return sorted({(a or {}).get("kind", "") for a in items if isinstance(a, dict)})


async def agent_synthesize_node(state: LearningState) -> LearningState:
    steps: List[dict] = list(state.get("plan", {}).get("steps") or [])
    produced: List[Dict[str, Any]] = list(state.get("artifacts") or [])

    related: Dict[str, Any] = dict((state.get("related") or {}))
    hints: Dict[str, str] = dict((state.get("hints") or {}))
    ctx_blob: Dict[str, Any] = dict(state.get("context") or {})

    logger.info(
        "agent_synthesize.state_in",
        extra={
            "artifacts_count": len(produced),
            "artifacts_preview": _preview(produced),
            "kinds": _kinds(produced),
        },
    )

    logs: List[str] = []
    agent = GenericKindAgent()

    for step in steps:
        if (step.get("type") or "").lower() != "capability":
            continue

        sid = step.get("id") or "step"
        emits: List[str] = [e for e in (step.get("emits") or []) if isinstance(e, str)]

        ctx_env = {
            "avc": (ctx_blob.get("avc") or {}),
            "fss": (ctx_blob.get("fss") or {}),
            "pss": (ctx_blob.get("pss") or {}),
            "artifacts": {"items": list(produced)},
            "related": dict(related.get(sid) or {}),
            "context_hint": hints.get(sid, ""),
            "tool_outputs": dict(ctx_blob.get("tool_outputs") or {}),
        }

        logger.info(
            "agent_synthesize.request",
            extra={
                "id": sid,
                "emits": emits,
                "has_related": bool(ctx_env["related"].get("hard") or ctx_env["related"].get("soft")),
                "has_hint": bool(ctx_env.get("context_hint")),
                "produced_so_far": len(produced),
            },
        )

        for kind in emits:
            params = {"kind": kind, "name": kind.split(".")[-1].replace("_", " ").title()}

            try:
                result = await agent.run(ctx_env, params)
                logger.info("agent_synthesize.raw_result", extra={"id": sid, "kind": kind, "result": result})
            except Exception as e:
                logs.append(f"{sid}:{kind}: ERROR {e}")
                logger.warning("agent_synthesize.error", extra={"id": sid, "kind": kind, "error": str(e)})
                continue

            emitted: List[dict] = []
            dropped = 0
            for p in (result.get("patches") or []):
                if p.get("op") == "upsert" and p.get("path") == "/artifacts":
                    vals = [v for v in (p.get("value") or []) if isinstance(v, dict)]
                    sanitized: List[dict] = []
                    for v in vals:
                        v_kind = str(v.get("kind") or "")
                        if v_kind != kind:
                            dropped += 1
                            logger.info(
                                "agent_synthesize.drop_unknown_kind",
                                extra={"id": sid, "expected": kind, "got": v_kind},
                            )
                            continue
                        v_name = v.get("name")
                        if not isinstance(v_name, str) or not v_name.strip():
                            v["name"] = params["name"]
                        sanitized.append(v)
                    if sanitized:
                        produced.extend(sanitized)
                        emitted.extend(sanitized)

            logs.append(f"{sid}:{kind}: generated={len(emitted)} dropped_kinds={dropped}")
            logger.info(
                "agent_synthesize.result",
                extra={
                    "id": sid,
                    "kind": kind,
                    "emitted_count": len(emitted),
                    "dropped_kinds": dropped,
                    "emitted_preview": _preview(emitted),
                    "kinds_total_so_far": _kinds(produced),
                },
            )

    # Visible summary line for the run logs
    logs.append(f"agent_synthesize: total_artifacts={len(produced)} kinds={_kinds(produced)}")

    logger.info(
        "agent_synthesize.done",
        extra={
            "total_artifacts": len(produced),
            "final_kinds": _kinds(produced),
            "artifacts_preview": _preview(produced),
        },
    )
    return {
        "artifacts": produced,
        "logs": logs,
    }
