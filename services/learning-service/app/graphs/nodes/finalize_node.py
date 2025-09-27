# services/learning-service/app/graphs/nodes/finalize_node.py
from __future__ import annotations

import os
import json
import base64
import hashlib
import logging
from datetime import datetime, date
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import UUID4

from app.clients.artifact_service import ArtifactServiceClient
from app.db.runs import mark_run_status, set_run_summary_times, append_notes_md
from app.agents.report_builder import artifact_counts_md, run_footer_md
from app.infra.rabbit import publish_event_v1
from app.models.events import LearningRunCompleted, LearningRunCompletedInterim

logger = logging.getLogger("app.graphs.nodes.finalize")


def _flatten_envelopes(produced: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for items in (produced or {}).values():
        if not items:
            continue
        flat.extend(items)
    return flat


def _stable_hash(payload: Any, n: int = 10) -> str:
    try:
        s = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        s = repr(payload)
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


def _derive_name(kind: str, data: Dict[str, Any]) -> str:
    kind = kind or ""
    data = data or {}

    if kind == "cam.asset.repo_snapshot":
        repo = (data.get("repo") or "").rstrip("/")
        base = os.path.basename(repo) or repo or "repo"
        commit = (data.get("commit") or "")[:12]
        return f"{base}@{commit}" if commit else base

    if kind == "cam.asset.source_index":
        root = (data.get("root") or "").rstrip("/")
        base = os.path.basename(root) or root or "source"
        return f"source-index:{base}"

    if kind == "cam.cobol.program":
        pid = data.get("program_id")
        if pid:
            return pid
        rel = (data.get("source") or {}).get("relpath")
        if rel:
            return os.path.splitext(os.path.basename(rel))[0] or rel
        return f"program:{_stable_hash(data)}"

    if kind == "cam.cobol.copybook":
        return data.get("name") or (data.get("source") or {}).get("relpath") or "copybook"

    return data.get("name") or (data.get("source") or {}).get("relpath") or kind or "artifact"


def _derive_identity(kind: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Provide a stable identity for kinds that typically key off a natural identity.
    """
    data = data or {}
    if kind == "cam.asset.repo_snapshot":
        repo = data.get("repo")
        commit = data.get("commit")
        if repo and commit:
            return {"repo": repo, "commit": commit}
        if repo:
            return {"repo": repo}
        return None

    if kind == "cam.asset.source_index":
        root = data.get("root")
        if root:
            return {"root": root}
        return None

    if kind == "cam.cobol.program":
        pid = data.get("program_id")
        if pid:
            return {"program_id": pid}
        rel = (data.get("source") or {}).get("relpath")
        if rel:
            return {"source": {"relpath": rel}}
        return {"hash": _stable_hash(data, n=16)}

    if kind == "cam.cobol.copybook":
        name = data.get("name")
        if name:
            return {"name": name}
        rel = (data.get("source") or {}).get("relpath")
        if rel:
            return {"source": {"relpath": rel}}
        return None

    name = data.get("name")
    if name:
        return {"name": name}
    rel = (data.get("source") or {}).get("relpath")
    if rel:
        return {"source": {"relpath": rel}}
    return None


def _json_sanitize(x: Any) -> Any:
    """
    Recursively coerce objects into JSON-serializable shapes.
    """
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    if isinstance(x, (datetime, date)):
        return x.isoformat()
    if isinstance(x, UUID):
        return str(x)
    if isinstance(x, bytes):
        return base64.b64encode(x).decode("ascii")
    if isinstance(x, (list, tuple, set)):
        return [_json_sanitize(v) for v in x]
    if isinstance(x, dict):
        return {str(k): _json_sanitize(v) for k, v in x.items()}
    # pydantic models / dataclasses fallback
    if hasattr(x, "model_dump"):
        try:
            return _json_sanitize(x.model_dump())
        except Exception:
            return _json_sanitize(dict(x))
    if hasattr(x, "__dict__"):
        try:
            return _json_sanitize(vars(x))
        except Exception:
            return str(x)
    return str(x)


def _safe_json_or_none(obj: Any) -> Optional[Any]:
    """
    Return a JSON-serializable version of obj, or None if it still can't be encoded.
    """
    try:
        san = _json_sanitize(obj)
        json.dumps(san, sort_keys=True)  # validate encodability
        return san
    except Exception:
        return None


def _envelope_to_item(env: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map our internal envelope to artifact-service upsert-batch item shape.
    We populate both 'data' and 'body' for compatibility, ensure identity,
    and sanitize 'diagrams' to avoid non-JSON types (e.g., datetime).
    """
    kind = env.get("kind_id") or env.get("kind")
    if not kind:
        return {}

    raw_data = env.get("data") or env.get("body") or {}
    data = _json_sanitize(raw_data)

    name = env.get("name") or _derive_name(kind, data)
    ver = str(env.get("schema_version") or env.get("version") or "1.0.0")

    item: Dict[str, Any] = {
        "name": name,
        "kind": kind,
        "kind_id": kind,           # compat
        "schema_version": ver,     # canonical
        "data": data,              # newer servers
        "body": data,              # older servers
    }

    # include a semver-ish 'version' only for compatibility
    if isinstance(env.get("version"), str) or ("." in ver):
        item["version"] = ver

    identity = env.get("identity")
    if not isinstance(identity, dict):
        identity = None
    if not identity:
        identity = _derive_identity(kind, data)
    if identity:
        item["identity"] = identity

    # tags
    tags = env.get("tags")
    if tags is not None:
        if not isinstance(tags, list):
            tags = [str(tags)]
        item["tags"] = tags

    # diagrams (sanitize; drop if still not JSON-able)
    diagrams = env.get("diagrams")
    if diagrams:
        safe_diagrams = _safe_json_or_none(diagrams)
        if safe_diagrams is not None:
            item["diagrams"] = safe_diagrams
        else:
            try:
                logger.warning(
                    "finalize: dropping non-JSON diagrams for %s/%s",
                    kind, name
                )
            except Exception:
                pass

    return item


async def finalize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Persist baseline (if strategy == baseline) to artifact-service.
    Finalize times and mark status, append a footer to notes.
    Also emits both the interim 'completed' (B) and final 'completed' (A) events.
    """
    run_id = state["run_id"]
    workspace_id: UUID4 = state["workspace_id"]
    strategy = state.get("strategy")
    produced: Dict[str, List[Dict[str, Any]]] = state.get("produced", {}) or {}

    # Aggregate counts for notes
    total_by_kind = {k: len(v or []) for k, v in produced.items()}
    await append_notes_md(run_id, artifact_counts_md(total_by_kind))

    # Persist baseline if applicable
    if strategy == "baseline" and produced:
        items: List[Dict[str, Any]] = []
        for env in _flatten_envelopes(produced):
            if not env:
                continue
            item = _envelope_to_item(env)
            if item:
                items.append(item)

        if items:
            # Preview log
            try:
                names_preview = [f"{it.get('kind')}/{it.get('name')}" for it in items]
                logger.info("finalize: upserting %d item(s): %s", len(items), names_preview[:20])
            except Exception:
                pass

            # Upsert & surface per-item results so failures aren't silent
            async with ArtifactServiceClient() as arts:
                try:
                    resp = await arts.upsert_batch(
                        workspace_id,
                        items,
                        correlation_id=state.get("correlation_id"),
                        run_id=str(run_id),
                    )
                except Exception as e:
                    logger.exception("finalize: upsert-batch failed hard: %s", e)
                    resp = None

            # Summarize server results (shape tolerant)
            try:
                results = None
                if isinstance(resp, dict) and "results" in resp:
                    results = resp.get("results")
                elif isinstance(resp, list):
                    results = resp

                if results is not None:
                    ok = 0
                    fail = 0
                    first_err: Optional[str] = None
                    for r in results:
                        success = bool(r.get("ok") or r.get("success") or r.get("status") in (200, "ok", "created", "updated"))
                        if success:
                            ok += 1
                        else:
                            fail += 1
                            if first_err is None:
                                err = r.get("error") or r.get("message") or r.get("reason") or r
                                first_err = err if isinstance(err, str) else json.dumps(err, default=str)
                    logger.info("finalize: upsert result: ok=%d fail=%d%s",
                                ok, fail, f" first_error={first_err}" if first_err else "")
                else:
                    logger.info("finalize: upsert result (raw, unknown shape)=%s",
                                json.dumps(resp, default=str)[:800] if resp is not None else "None")
            except Exception:
                pass

    # Emit interim 'completed' (B) with deltas.counts
    try:
        counts = (((state.get("deltas") or {}).get("counts")) or {})
        interim = LearningRunCompletedInterim(
            run_id=run_id,
            workspace_id=workspace_id,
            playbook_id=state["playbook_id"],
            artifact_ids=[],  # learning-service does not track persisted IDs here
            artifact_failures=list(state.get("errors") or []),
            validations=list(state.get("validations") or []),
            deltas={
                "counts": {
                    k: int(counts.get(k, 0))
                    for k in ("new", "updated", "unchanged", "retired", "added", "changed", "removed")
                }
            },
        )
        headers = {}
        if state.get("correlation_id"):
            headers["x-correlation-id"] = state["correlation_id"]
        await publish_event_v1(event="completed", payload=interim.model_dump(mode="json"), headers=headers)
    except Exception:
        pass

    # Always finalize times/status, even if no artifacts
    now = datetime.utcnow()
    await set_run_summary_times(run_id, completed_at=now)
    await mark_run_status(run_id, "completed")
    await append_notes_md(run_id, run_footer_md(now))

    # Emit final 'completed' (A)
    started_at = state.get("started_at") or now
    final_evt = LearningRunCompleted(
        run_id=run_id,
        workspace_id=workspace_id,
        playbook_id=state["playbook_id"],
        artifact_ids=[],
        validations=list(state.get("validations") or []),
        started_at=started_at,
        completed_at=now,
        duration_s=(now - started_at).total_seconds(),
        title=state.get("title"),
        description=state.get("description"),
    )
    headers = {}
    if state.get("correlation_id"):
        headers["x-correlation-id"] = state["correlation_id"]
    await publish_event_v1(event="completed", payload=final_evt.model_dump(mode="json"), headers=headers)

    return state
