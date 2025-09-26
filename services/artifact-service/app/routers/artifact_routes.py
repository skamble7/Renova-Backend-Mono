# services/artifact-service/app/routers/artifact_routes.py
from __future__ import annotations

from copy import deepcopy
import logging
from typing import Optional, List, Dict, Any

import jsonpatch
from fastapi import APIRouter, HTTPException, Header, Query, Response, status
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel

from ..config import settings
from ..db.mongodb import get_db
from ..events.rabbit import publish_event_v1
from ..dal import artifact_dal as dal
from ..models.artifact import (
    ArtifactItemCreate,
    ArtifactItemReplace,
    ArtifactItemPatchIn,
    WorkspaceArtifactsDoc,
)
# Renova common events (same API shape as Raina)
from libs.renova_common.events import Service
from ..services.registry_service import KindRegistryService, SchemaValidationError

logger = logging.getLogger("app.routes.artifact")

router = APIRouter(
    prefix="/artifact",
    tags=["artifact"],
    default_response_class=ORJSONResponse,
)

def _set_event_header(response: Response, published: bool) -> None:
    response.headers["X-Event-Published"] = "true" if published else "false"

def _org() -> str:
    return settings.events_org  # default should be "renova"

# ─────────────────────────────────────────────────────────────
# Create/Upsert single artifact (versioned + lineage)
# ─────────────────────────────────────────────────────────────
@router.post("/{workspace_id}")
async def upsert_artifact(
    workspace_id: str,
    body: ArtifactItemCreate,
    response: Response,
    run_id: Optional[str] = Header(default=None, alias="X-Run-Id"),
):
    db = await get_db()
    svc = KindRegistryService(db)

    try:
        env = await svc.build_envelope(
            kind_or_alias=body.kind,
            name=body.name,
            data=body.data,
            supplied_schema_version=None,
        )
        payload = ArtifactItemCreate(
            kind=env["kind"],
            name=env["name"],
            data=env["data"],
            diagrams=body.diagrams,               # NEW: pass diagrams through
            natural_key=env["natural_key"],
            fingerprint=env["fingerprint"],
            provenance=body.provenance,
        )
        art, op = await dal.upsert_artifact(
            db=db,
            workspace_id=workspace_id,
            payload=payload,
            prov=body.provenance,
            run_id=run_id,
        )
    except SchemaValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("upsert_artifact_failed", extra={"workspace_id": workspace_id, "err": str(e)})
        raise HTTPException(status_code=500, detail="Artifact upsert failed")

    published = True
    if op == "insert":
        published = publish_event_v1(org=_org(), service=Service.ARTIFACT, event="created", payload=art.model_dump())
    elif op == "update":
        published = publish_event_v1(org=_org(), service=Service.ARTIFACT, event="updated", payload=art.model_dump())

    response.headers["ETag"] = str(art.version)
    response.headers["X-Op"] = op
    _set_event_header(response, published)

    status_code = status.HTTP_201_CREATED if op == "insert" else status.HTTP_200_OK
    return ORJSONResponse(art.model_dump(), status_code=status_code)


# ─────────────────────────────────────────────────────────────
# Batch upsert
# ─────────────────────────────────────────────────────────────
class BatchItems(BaseModel):
    items: List[ArtifactItemCreate]

@router.post("/{workspace_id}/upsert-batch")
async def upsert_batch(
    workspace_id: str,
    payload: BatchItems,
    response: Response,
    run_id: Optional[str] = Header(default=None, alias="X-Run-Id"),
):
    db = await get_db()
    svc = KindRegistryService(db)

    results: List[Dict[str, Any]] = []
    counts = {"insert": 0, "update": 0, "noop": 0, "failed": 0}

    for item in payload.items:
        try:
            env = await svc.build_envelope(
                kind_or_alias=item.kind,
                name=item.name,
                data=item.data,
                supplied_schema_version=None,
            )
            create = ArtifactItemCreate(
                kind=env["kind"],
                name=env["name"],
                data=env["data"],
                diagrams=item.diagrams,             # NEW: pass diagrams through
                natural_key=env["natural_key"],
                fingerprint=env["fingerprint"],
                provenance=item.provenance,
            )
            art, op = await dal.upsert_artifact(db, workspace_id, create, item.provenance, run_id=run_id)
            if op in counts:
                counts[op] += 1
            results.append({
                "artifact_id": art.artifact_id,
                "natural_key": art.natural_key,
                "op": op,
                "version": art.version,
                "schema_version": env.get("schema_version"),
                "kind": env.get("kind"),
                "name": env.get("name"),
            })
            if op == "insert":
                publish_event_v1(org=_org(), service=Service.ARTIFACT, event="created", payload=art.model_dump())
            elif op == "update":
                publish_event_v1(org=_org(), service=Service.ARTIFACT, event="updated", payload=art.model_dump())

        except SchemaValidationError as e:
            counts["failed"] += 1
            results.append({"error": str(e) or repr(e), "kind": item.kind, "name": item.name})
        except Exception as e:
            counts["failed"] += 1
            logger.exception("batch_upsert_failed_item", extra={"workspace_id": workspace_id, "kind": getattr(item, "kind", None)})
            results.append({"error": str(e) or repr(e), "kind": item.kind, "name": item.name})

    summary = {"counts": counts, "results": results}
    response.headers["X-Batch-Inserted"] = str(counts["insert"])
    response.headers["X-Batch-Updated"] = str(counts["update"])
    response.headers["X-Batch-Noop"] = str(counts["noop"])
    response.headers["X-Batch-Failed"] = str(counts["failed"])
    return summary


# ─────────────────────────────────────────────────────────────
# Baseline inputs
# ─────────────────────────────────────────────────────────────
class InputsBaselineIn(BaseModel):
    avc: Dict[str, Any]
    fss: Dict[str, Any]
    pss: Dict[str, Any]

class InputsBaselinePatch(BaseModel):
    avc: Optional[Dict[str, Any]] = None
    pss: Optional[Dict[str, Any]] = None
    fss_stories_upsert: Optional[List[Dict[str, Any]]] = None

@router.post("/{workspace_id}/baseline-inputs")
async def set_baseline_inputs(
    workspace_id: str,
    body: InputsBaselineIn,
    response: Response,
    if_absent_only: bool = Query(default=False),
    expected_version: Optional[int] = Query(default=None, ge=1),
):
    db = await get_db()
    try:
        parent, op = await dal.set_inputs_baseline(
            db=db,
            workspace_id=workspace_id,
            new_inputs=body.model_dump(),
            if_absent_only=if_absent_only,
            expected_version=expected_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=412, detail=str(e))
    except Exception as e:
        logger.exception("set_baseline_inputs_failed", extra={"workspace_id": workspace_id, "err": str(e)})
        raise HTTPException(status_code=500, detail="Failed to set baseline inputs")

    published = True
    if op == "insert":
        published = publish_event_v1(
            org=_org(), service=Service.ARTIFACT, event="baseline_inputs.set",
            payload={
                "workspace_id": workspace_id,
                "version": parent.baseline_version,
                "fingerprint": parent.baseline_fingerprint,
                "op": op,
            },
        )
    elif op == "replace":
        published = publish_event_v1(
            org=_org(), service=Service.ARTIFACT, event="baseline_inputs.replaced",
            payload={
                "workspace_id": workspace_id,
                "version": parent.baseline_version,
                "fingerprint": parent.baseline_fingerprint,
                "op": op,
            },
        )

    _set_event_header(response, published)
    response.headers["X-Op"] = op
    response.headers["X-Baseline-Version"] = str(parent.baseline_version)
    return parent.model_dump(by_alias=True)


@router.patch("/{workspace_id}/baseline-inputs")
async def patch_baseline_inputs(
    workspace_id: str,
    body: InputsBaselinePatch,
    response: Response,
    expected_version: Optional[int] = Query(default=None, ge=1),
):
    db = await get_db()
    try:
        updated = await dal.merge_inputs_baseline(
            db=db,
            workspace_id=workspace_id,
            avc=body.avc,
            pss=body.pss,
            fss_stories_upsert=body.fss_stories_upsert,
            expected_version=expected_version,
        )
    except ValueError as e:
        raise HTTPException(status_code=412, detail=str(e))
    except Exception as e:
        logger.exception("patch_baseline_inputs_failed", extra={"workspace_id": workspace_id, "err": str(e)})
        raise HTTPException(status_code=500, detail="Failed to patch baseline inputs")

    published = publish_event_v1(
        org=_org(), service=Service.ARTIFACT, event="baseline_inputs.merged",
        payload={
            "workspace_id": workspace_id,
            "version": updated.baseline_version,
            "fingerprint": updated.baseline_fingerprint,
            "upserts": len(body.fss_stories_upsert or []),
            "replaced_avc": body.avc is not None,
            "replaced_pss": body.pss is not None,
        },
    )
    _set_event_header(response, published)
    response.headers["X-Baseline-Version"] = str(updated.baseline_version)
    return updated.model_dump(by_alias=True)


# ─────────────────────────────────────────────────────────────
# List / Parent / Deltas / Read / HEAD / Replace / Patch / History / Delete
# ─────────────────────────────────────────────────────────────
@router.get("/{workspace_id}")
async def list_artifacts(
    workspace_id: str,
    kind: Optional[str] = Query(default=None, description="Filter by Artifact kind"),
    name_prefix: Optional[str] = Query(default=None, description="Case-insensitive prefix"),
    include_deleted: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    db = await get_db()
    items = await dal.list_artifacts(
        db,
        workspace_id=workspace_id,
        kind=kind,
        name_prefix=name_prefix,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return items


@router.get("/{workspace_id}/parent", response_model=WorkspaceArtifactsDoc)
async def get_workspace_with_artifacts(
    workspace_id: str,
    include_deleted: bool = Query(default=False, description="Include soft-deleted artifacts"),
):
    db = await get_db()
    doc = await dal.get_parent_doc(db, workspace_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Workspace parent not found")

    if include_deleted:
        return doc

    filtered = [a for a in doc.artifacts if a.deleted_at is None]
    return doc.model_copy(update={"artifacts": filtered}, deep=True)


@router.get("/{workspace_id}/deltas")
async def run_deltas(
    workspace_id: str,
    run_id: str = Query(..., description="Relearning run id to compute deltas for"),
    include_ids: bool = Query(default=False, description="Include grouped artifact ids"),
):
    db = await get_db()
    parent = await dal.get_parent_doc(db, workspace_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Workspace parent not found")

    out = dal.compute_run_deltas(parent, run_id=run_id, include_ids=include_ids)
    return out


@router.get("/{workspace_id}/{artifact_id}")
async def get_artifact(workspace_id: str, artifact_id: str, response: Response):
    db = await get_db()
    art = await dal.get_artifact(db, workspace_id, artifact_id)
    if not art or art.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Not found")
    response.headers["ETag"] = str(art.version)
    return art

@router.head("/{workspace_id}/{artifact_id}")
async def head_artifact(workspace_id: str, artifact_id: str, response: Response):
    db = await get_db()
    art = await dal.get_artifact(db, workspace_id, artifact_id)
    if not art or art.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Not found")
    response.headers["ETag"] = str(art.version)
    return Response(status_code=status.HTTP_200_OK)


def _parse_if_match(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="If-Match must be an integer version")

def _guard_if_match(expected: Optional[int], actual: int) -> None:
    if expected is not None and expected != actual:
        raise HTTPException(
            status_code=412,
            detail=f"Precondition Failed: expected version {expected}, actual {actual}",
        )

@router.put("/{workspace_id}/{artifact_id}")
async def replace_artifact(
    workspace_id: str,
    artifact_id: str,
    body: ArtifactItemReplace,
    response: Response,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
):
    db = await get_db()
    art = await dal.get_artifact(db, workspace_id, artifact_id)
    if not art or art.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Not found")

    expected = _parse_if_match(if_match)
    _guard_if_match(expected, art.version)

    # Allow replacing data and/or diagrams
    updated = await dal.replace_artifact(
        db,
        workspace_id,
        artifact_id,
        new_data=body.data,
        prov=body.provenance,
        new_diagrams=body.diagrams,          # NEW: optional diagrams
    )

    published = publish_event_v1(org=_org(), service=Service.ARTIFACT, event="updated", payload=updated.model_dump())
    response.headers["ETag"] = str(updated.version)
    _set_event_header(response, published)
    return updated

@router.post("/{workspace_id}/{artifact_id}/patch")
async def patch_artifact(
    workspace_id: str,
    artifact_id: str,
    body: ArtifactItemPatchIn,
    response: Response,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
):
    db = await get_db()
    art = await dal.get_artifact(db, workspace_id, artifact_id)
    if not art or art.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Not found")

    expected = _parse_if_match(if_match)
    _guard_if_match(expected, art.version)

    try:
        new_data = jsonpatch.apply_patch(deepcopy(art.data), body.patch, in_place=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid patch: {e}")

    from_version = art.version
    updated = await dal.replace_artifact(
        db,
        workspace_id,
        artifact_id,
        new_data=new_data,
        prov=body.provenance,
        # diagrams not patched here
    )
    await dal.record_patch(
        db,
        workspace_id=workspace_id,
        artifact_id=artifact_id,
        from_version=from_version,
        to_version=updated.version,
        patch=body.patch,
        prov=body.provenance,
    )

    published = publish_event_v1(
        org=_org(), service=Service.ARTIFACT, event="patched",
        payload={
            "artifact": updated.model_dump(),
            "from_version": from_version,
            "to_version": updated.version,
            "patch": body.patch
        }
    )

    response.headers["ETag"] = str(updated.version)
    _set_event_header(response, published)
    return updated

@router.get("/{workspace_id}/{artifact_id}/history")
async def history(workspace_id: str, artifact_id: str):
    db = await get_db()
    art = await dal.get_artifact(db, workspace_id, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Not found")
    return await dal.list_patches(db, workspace_id, artifact_id)

@router.delete("/{workspace_id}/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact(workspace_id: str, artifact_id: str, response: Response):
    db = await get_db()
    deleted = await dal.soft_delete_artifact(db, workspace_id, artifact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Not found or already deleted")

    published = publish_event_v1(
        org=_org(), service=Service.ARTIFACT, event="deleted",
        payload={"_id": artifact_id, "workspace_id": workspace_id},
    )
    _set_event_header(response, published)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
