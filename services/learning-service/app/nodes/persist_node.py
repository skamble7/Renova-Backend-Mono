# services/learning-service/app/nodes/persist_node.py
from __future__ import annotations

import os
import math
import asyncio
import logging
from typing import Any, Dict, List

from app.models.state import LearningState
from app.clients import artifact_service

log = logging.getLogger("app.nodes.persist")

# Tunables
BATCH_SIZE = int(os.getenv("PERSIST_BATCH_SIZE", "40"))          # items per upsert call
MAX_RETRIES = int(os.getenv("PERSIST_RETRIES", "3"))             # attempts per chunk
BASE_DELAY = float(os.getenv("PERSIST_RETRY_BASE_DELAY", "0.5")) # seconds; exponential backoff

async def _upsert_with_retry(workspace_id: str, items: List[Dict[str, Any]], run_id: str) -> Dict[str, Any]:
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await artifact_service.upsert_batch(workspace_id, items, run_id=run_id)
        except Exception as e:
            last_err = e
            # Exponential backoff with jitter
            delay = BASE_DELAY * (2 ** (attempt - 1))
            jitter = min(0.25, delay * 0.1)
            wait = delay + (jitter if attempt < MAX_RETRIES else 0)
            log.warning(
                "persist.chunk.retry",
                extra={"attempt": attempt, "max": MAX_RETRIES, "size": len(items), "error": str(e), "sleep": wait},
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(wait)
    # All attempts failed
    if last_err:
        raise last_err
    return {}

async def persist_node(state: LearningState) -> LearningState:
    """
    Upsert artifacts into the workspace and expose the resulting IDs.
    Uses chunking + retry to avoid timeouts on large batches.
    """
    workspace_id = str(state.get("workspace_id") or "")
    run_id = str((state.get("context") or {}).get("run_id") or state.get("run_id") or "")
    arts: List[Dict[str, Any]] = list(state.get("artifacts") or [])

    if not workspace_id:
        log.warning("persist.missing_workspace_id")
        return {"run_artifact_ids": [], "logs": ["persist: skipped (no workspace_id)"]}

    if not arts:
        log.info("persist.no_artifacts")
        return {"run_artifact_ids": [], "logs": ["persist: no artifacts to persist"]}

    # Prepare payloads
    items: List[Dict[str, Any]] = []
    for a in arts:
        kind = (a.get("kind") or "cam.document").strip()
        name = (a.get("name") or kind).strip()
        items.append({
            "kind": kind,
            "name": name,
            "data": a.get("data") or {},
            "natural_key": f"{kind}:{name}".lower(),
            "provenance": {"author": "learning-service", "run_id": run_id},
            "tags": ["generated", "learning"],
        })

    # Chunk + upsert
    total = len(items)
    batch_size = max(1, BATCH_SIZE)
    chunks = math.ceil(total / batch_size)
    all_ids: List[str] = []
    logs: List[str] = []

    log.info("persist.start", extra={"total": total, "batch_size": batch_size, "chunks": chunks})

    for i in range(chunks):
        start = i * batch_size
        end = min(start + batch_size, total)
        chunk = items[start:end]
        try:
            resp = await _upsert_with_retry(workspace_id, chunk, run_id)
        except Exception as e:
            # If a chunk repeatedly times out, degrade to single-item upserts to salvage progress
            log.error("persist.chunk.failed", extra={"index": i + 1, "chunks": chunks, "size": len(chunk), "error": str(e)})
            logs.append(f"persist: chunk {i+1}/{chunks} ERROR {e}; degrading to singles")
            for idx, one in enumerate(chunk, start=1):
                try:
                    resp1 = await _upsert_with_retry(workspace_id, [one], run_id)
                    if isinstance(resp1, dict):
                        for r in resp1.get("results") or []:
                            aid = r.get("artifact_id") or r.get("id") or (r.get("artifact") or {}).get("_id")
                            if aid:
                                all_ids.append(str(aid))
                except Exception as e1:
                    log.error("persist.single.failed", extra={"error": str(e1), "name": one.get("name"), "kind": one.get("kind")})
                    logs.append(f"persist: single '{one.get('kind')}:{one.get('name')}' ERROR {e1}")
            # continue to next chunk
            continue

        # Normal path: collect IDs
        if isinstance(resp, dict):
            got = 0
            for r in resp.get("results") or []:
                aid = r.get("artifact_id") or r.get("id") or (r.get("artifact") or {}).get("_id")
                if aid:
                    all_ids.append(str(aid))
                    got += 1
            log.info("persist.chunk.ok", extra={"index": i + 1, "chunks": chunks, "size": len(chunk), "ids": got})
            logs.append(f"persist: chunk {i+1}/{chunks} saved={got}")

    log.info("persist.result", extra={"saved": len(all_ids)})
    logs.append(f"persist: saved_total={len(all_ids)}")

    return {"run_artifact_ids": all_ids, "logs": logs}
