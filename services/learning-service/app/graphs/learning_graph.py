# services/learning-service/app/graphs/learning_graph.py
from __future__ import annotations

import json
import logging
import os
from typing import Callable, Awaitable, Any, Dict, List

from langgraph.graph import StateGraph, END

from app.models.state import LearningState
from app.nodes.ingest_node import ingest_node
from app.nodes.plan_node import plan_node
from app.nodes.resolve_dependencies_node import resolve_dependencies_node
from app.nodes.tool_exec_node import tool_exec_node
from app.nodes.artifact_assembly_node import artifact_assembly_node  # optional; no-op if not used
from app.nodes.context_assembly_node import context_assembly_node
from app.nodes.agent_synthesize_node import agent_synthesize_node
from app.nodes.post_synthesize_debug_node import post_synthesize_debug_node  # NEW
from app.nodes.validate_node import validate_node
from app.nodes.persist_node import persist_node                              # NEW
from app.nodes.classify_after_persist_node import classify_after_persist_node
from app.nodes.publish_node import publish_node

logger = logging.getLogger("app.graphs.learning_graph")

# Controls how much we dump into logs
_MAX_PREVIEW_ITEMS = int(os.getenv("LEARNING_LOG_MAX_ARTIFACTS", "50"))
_MAX_VALUE_CHARS = int(os.getenv("LEARNING_LOG_MAX_VALUE_CHARS", "800"))
_PRETTY = os.getenv("LEARNING_LOG_PRETTY_JSON", "0") == "1"


def _trim_val(v: Any, max_chars: int = _MAX_VALUE_CHARS) -> Any:
    try:
        if isinstance(v, (dict, list)):
            s = json.dumps(v, ensure_ascii=False)
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


def _artifact_preview(items: List[dict], max_items: int = _MAX_PREVIEW_ITEMS) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for a in (items or [])[:max_items]:
        if not isinstance(a, dict):
            continue
        out.append({
            "kind": a.get("kind"),
            "name": a.get("name"),
            "data_preview": _trim_val(a.get("data")),
        })
    return out


def _snapshot_state(state: LearningState) -> Dict[str, Any]:
    arts: List[dict] = list(state.get("artifacts") or [])
    snap = {
        "artifacts_count": len(arts),
        "artifacts_preview": _artifact_preview(arts),
        "keys": sorted(list(state.keys())),
    }
    return snap


def _wrap_node(node_name: str, fn: Callable[[LearningState], Awaitable[LearningState]]):
    async def wrapped(state: LearningState) -> LearningState:
        try:
            snap_in = _snapshot_state(state)
            logger.info(
                f"graph.node.{node_name}.state_in",
                extra={"snapshot": snap_in}
                | ({"full_state": state} if os.getenv("LEARNING_LOG_FULL_STATE") == "1" else {}),
            )
        except Exception:
            logger.debug("graph.node.%s.state_in.log_failed", node_name, exc_info=True)

        out = await fn(state)

        merged: LearningState = dict(state)
        for k, v in (out or {}).items():
            if k == "logs":
                merged["logs"] = list(merged.get("logs") or []) + list(v or [])
            elif k == "artifacts":
                merged["artifacts"] = list(v or [])
            else:
                merged[k] = v

        try:
            snap_out = _snapshot_state(merged)
            logger.info(
                f"graph.node.{node_name}.state_out",
                extra={"snapshot": snap_out}
                | ({"delta": out} if os.getenv("LEARNING_LOG_NODE_DELTA") == "1" else {}),
            )
        except Exception:
            logger.debug("graph.node.%s.state_out.log_failed", node_name, exc_info=True)

        return out
    return wrapped


def build_graph() -> Callable[[LearningState], LearningState]:
    """
    Canonical learning pipeline (pack-agnostic):

      INGEST → PLAN → RESOLVE_DEPENDENCIES
            → TOOL_EXEC → ARTIFACT_ASSEMBLY
            → CONTEXT_ASSEMBLY → AGENT_SYNTHESIZE
            → POST_SYNTHESIZE_DEBUG → VALIDATE
            → PERSIST → CLASSIFY_AFTER_PERSIST → PUBLISH → END
    """
    sg = StateGraph(LearningState)

    # Core stages with state snapshot logging
    sg.add_node("ingest", _wrap_node("ingest", ingest_node))
    sg.add_node("plan", _wrap_node("plan", plan_node))
    sg.add_node("resolve_deps", _wrap_node("resolve_deps", resolve_dependencies_node))
    sg.add_node("tool_exec", _wrap_node("tool_exec", tool_exec_node))
    sg.add_node("artifact_assembly", _wrap_node("artifact_assembly", artifact_assembly_node))
    sg.add_node("context_assembly", _wrap_node("context_assembly", context_assembly_node))
    sg.add_node("agent_synthesize", _wrap_node("agent_synthesize", agent_synthesize_node))
    sg.add_node("post_synthesize_debug", _wrap_node("post_synthesize_debug", post_synthesize_debug_node))  # NEW
    sg.add_node("validate", _wrap_node("validate", validate_node))
    sg.add_node("persist", _wrap_node("persist", persist_node))                                            # NEW
    sg.add_node("classify_after_persist", _wrap_node("classify_after_persist", classify_after_persist_node))
    sg.add_node("publish", _wrap_node("publish", publish_node))

    # Edges
    sg.set_entry_point("ingest")
    sg.add_edge("ingest", "plan")
    sg.add_edge("plan", "resolve_deps")
    sg.add_edge("resolve_deps", "tool_exec")
    sg.add_edge("tool_exec", "artifact_assembly")
    sg.add_edge("artifact_assembly", "context_assembly")
    sg.add_edge("context_assembly", "agent_synthesize")
    sg.add_edge("agent_synthesize", "post_synthesize_debug")  # NEW
    sg.add_edge("post_synthesize_debug", "validate")          # NEW
    sg.add_edge("validate", "persist")                        # NEW
    sg.add_edge("persist", "classify_after_persist")          # NEW
    sg.add_edge("classify_after_persist", "publish")          # NEW
    sg.add_edge("publish", END)                               # NEW

    return sg.compile()
