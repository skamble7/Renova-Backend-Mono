# services/learning-service/app/graphs/nodes/preflight_node.py
from __future__ import annotations

from typing import Any, Dict, List
from pydantic import UUID4

from app.clients.artifact_service import ArtifactServiceClient


async def preflight_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    - Loads workspace baseline (parent doc) and indexes artifacts by kind.
    - Verifies that produced kinds exist in registry and pulls `depends_on` lists for each.
    Stores:
      state['baseline'] = { kind_id: [ArtifactEnvelope-like dicts] }
      state['depends'] = { kind_id: [depends_on kind ids] }
      state['kind_schema_version'] = { kind_id: version string }
    """
    workspace_id: UUID4 = state["workspace_id"]
    correlation_id = state.get("correlation_id")

    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    depends: Dict[str, List[str]] = {}
    schema_version: Dict[str, str] = {}

    async with ArtifactServiceClient() as arts:
        parent = await arts.get_workspace_parent(workspace_id, correlation_id=correlation_id)
        items = parent.get("artifacts") or parent.get("items") or []
        for a in items:
            k = a.get("kind") or a.get("kind_id")
            if not k:
                continue
            by_kind.setdefault(k, []).append(a)

        # Collect dependencies and default versions for each kind we will produce
        for step in state["plan"]["steps"]:
            for kind_id in step["produces_kinds"]:
                kind_doc = await arts.get_kind(kind_id, correlation_id=correlation_id)
                # Derive dependencies and schema version preference
                dep = []
                for sv in kind_doc.get("schema_versions", []):
                    if sv.get("version") == kind_doc.get("latest_schema_version"):
                        dep = list(sv.get("depends_on") or [])
                        break
                if not dep:
                    dep = list(kind_doc.get("depends_on") or [])  # also allow top-level
                depends[kind_id] = dep
                schema_version[kind_id] = str(kind_doc.get("latest_schema_version") or "1.0.0")

    state["baseline"] = by_kind
    state["baseline_meta"] = {"source": "artifact-service"}
    state["depends"] = depends
    state["kind_schema_version"] = schema_version
    return state
