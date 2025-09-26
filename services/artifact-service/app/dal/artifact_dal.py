# services/artifact-service/app/dal/artifact_dal.py
from __future__ import annotations

import json
import uuid
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Iterable

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, ReturnDocument

from ..models.artifact import (
    ArtifactItem,
    ArtifactItemCreate,
    ArtifactItemReplace,
    ArtifactItemPatchIn,
    WorkspaceArtifactsDoc,
    WorkspaceSnapshot,
    Provenance,
    Lineage,
    DiagramInstance,
)

WORKSPACE_ARTIFACTS = "workspace_artifacts"
PATCHES = "artifact_patches"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _canonical(data: Any) -> str:
    """Stable JSON for hashing/compare. Removes volatile keys if present."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _fallback_natural_key(kind: str, name: str) -> str:
    """If caller didn't compute per-kind natural key, fall back to kind+name."""
    return f"{kind}:{name}".lower().strip()

def _normalize_diagrams(diagrams: Optional[List[DiagramInstance]]) -> List[Dict[str, Any]]:
    """Convert Pydantic models to dicts and normalize missing → []."""
    if not diagrams:
        return []
    out: List[Dict[str, Any]] = []
    for d in diagrams:
        if isinstance(d, DiagramInstance):
            out.append(d.model_dump())
        else:
            # Accept raw dicts too (defensive)
            out.append(d)
    return out


# ─────────────────────────────────────────────────────────────
# Indexes
# ─────────────────────────────────────────────────────────────
async def ensure_indexes(db: AsyncIOMotorDatabase):
    col = db[WORKSPACE_ARTIFACTS]

    # One parent doc per workspace
    await col.create_index([("workspace_id", ASCENDING)], unique=True)

    # Artifacts lookup / merging
    await col.create_index([("artifacts.artifact_id", ASCENDING)])
    await col.create_index([("artifacts.natural_key", ASCENDING)])
    await col.create_index([("artifacts.fingerprint", ASCENDING)])
    await col.create_index([("artifacts.diagram_fingerprint", ASCENDING)])  # NEW
    await col.create_index([("artifacts.kind", ASCENDING), ("artifacts.name", ASCENDING)])
    await col.create_index([("artifacts.deleted_at", ASCENDING)])

    # Baseline inputs and metadata (useful filters)
    await col.create_index([("inputs_baseline_version", DESCENDING)])
    await col.create_index([("inputs_baseline_fingerprint", ASCENDING)])
    await col.create_index([("last_promoted_run_id", ASCENDING)])

    # Patch history
    await db[PATCHES].create_index(
        [("artifact_id", ASCENDING), ("workspace_id", ASCENDING), ("to_version", DESCENDING)]
    )


# ─────────────────────────────────────────────────────────────
# Parent doc lifecycle
# (unchanged)
# ─────────────────────────────────────────────────────────────
async def create_parent_doc(
    db: AsyncIOMotorDatabase,
    workspace: WorkspaceSnapshot,
    *,
    inputs_baseline: Optional[Dict[str, Any]] = None,
    inputs_baseline_version: int = 1,
    last_promoted_run_id: Optional[str] = None,
) -> WorkspaceArtifactsDoc:
    now = datetime.utcnow()
    fp = _sha256(_canonical(inputs_baseline)) if inputs_baseline else None
    doc = {
        "_id": str(uuid.uuid4()),
        "workspace_id": workspace.id,
        "workspace": workspace.model_dump(by_alias=True),
        "inputs_baseline": inputs_baseline or {},
        "inputs_baseline_fingerprint": fp,
        "inputs_baseline_version": inputs_baseline_version,
        "last_promoted_run_id": last_promoted_run_id,
        "artifacts": [],
        "created_at": now,
        "updated_at": now,
    }
    await db[WORKSPACE_ARTIFACTS].insert_one(doc)
    return WorkspaceArtifactsDoc(**doc)


async def get_parent_doc(db: AsyncIOMotorDatabase, workspace_id: str) -> Optional[WorkspaceArtifactsDoc]:
    d = await db[WORKSPACE_ARTIFACTS].find_one({"workspace_id": workspace_id})
    return WorkspaceArtifactsDoc(**d) if d else None


async def refresh_workspace_snapshot(db, workspace: WorkspaceSnapshot) -> bool:
    """Update the denormalized workspace snapshot inside the parent doc; create if missing."""
    now = datetime.utcnow()
    res = await db[WORKSPACE_ARTIFACTS].update_one(
        {"workspace_id": workspace.id},
        {
            "$set": {
                "workspace": workspace.model_dump(by_alias=True),
                "updated_at": now,
            }
        },
        upsert=False,
    )
    if res.matched_count == 0:
        await create_parent_doc(db, workspace)
    return True


async def delete_parent_doc(db, workspace_id: str) -> bool:
    res = await db[WORKSPACE_ARTIFACTS].delete_one({"workspace_id": workspace_id})
    return res.deleted_count == 1


# ─────────────────────────────────────────────────────────────
# Baseline inputs (unchanged)
# ─────────────────────────────────────────────────────────────
def _upsert_fss_stories(existing_stories: List[Dict[str, Any]], to_upsert: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    index = {s.get("key"): i for i, s in enumerate(existing_stories) if isinstance(s, dict) and s.get("key")}
    result = list(existing_stories)
    for s in to_upsert:
        k = s.get("key")
        if not k:
            continue
        if k in index:
            result[index[k]] = s  # replace whole story by key
        else:
            result.append(s)      # append new
    return result


async def set_inputs_baseline(
    db: AsyncIOMotorDatabase,
    workspace_id: str,
    new_inputs: Dict[str, Any],
    *,
    if_absent_only: bool = False,
    expected_version: Optional[int] = None,
) -> Tuple[WorkspaceArtifactsDoc, str]:
    """
    Set/replace the entire inputs_baseline.
    Returns: (updated_parent_doc, op) where op ∈ {"insert","replace","noop"}
    """
    now = datetime.utcnow()
    parent = await get_parent_doc(db, workspace_id)
    if not parent:
        raise ValueError(f"Workspace parent not found for {workspace_id}")

    existed = bool(parent.inputs_baseline)
    if if_absent_only and existed:
        return parent, "noop"

    if expected_version is not None and parent.inputs_baseline_version != expected_version:
        raise ValueError(
            f"Precondition Failed: expected baseline version {expected_version}, "
            f"actual {parent.inputs_baseline_version}"
        )

    fp = _sha256(_canonical(new_inputs))

    res = await db[WORKSPACE_ARTIFACTS].find_one_and_update(
        {"workspace_id": workspace_id},
        {
            "$set": {
                "inputs_baseline": new_inputs,
                "inputs_baseline_fingerprint": fp,
                "updated_at": now,
            },
            "$inc": {"inputs_baseline_version": 1 if existed else 0},
        },
        return_document=ReturnDocument.AFTER,
    )
    return WorkspaceArtifactsDoc(**res), ("replace" if existed else "insert")


async def merge_inputs_baseline(
    db: AsyncIOMotorDatabase,
    workspace_id: str,
    *,
    avc: Optional[Dict[str, Any]] = None,
    pss: Optional[Dict[str, Any]] = None,
    fss_stories_upsert: Optional[List[Dict[str, Any]]] = None,
    expected_version: Optional[int] = None,
) -> WorkspaceArtifactsDoc:
    """
    Partial baseline merge:
      - avc: replace whole AVC if provided
      - pss: replace whole PSS if provided
      - fss_stories_upsert: upsert by story.key into baseline.fss.stories
    Always bumps inputs_baseline_version by 1 when any change is applied.
    """
    now = datetime.utcnow()
    parent = await get_parent_doc(db, workspace_id)
    if not parent:
        raise ValueError(f"Workspace parent not found for {workspace_id}")

    if expected_version is not None and parent.inputs_baseline_version != expected_version:
        raise ValueError(
            f"Precondition Failed: expected baseline version {expected_version}, "
            f"actual {parent.inputs_baseline_version}"
        )

    base = parent.inputs_baseline or {}
    changed = False

    if avc is not None:
        base["avc"] = avc
        changed = True
    if pss is not None:
        base["pss"] = pss
        changed = True
    if fss_stories_upsert:
        fss = base.get("fss") or {}
        stories = fss.get("stories") or []
        merged = _upsert_fss_stories(stories, fss_stories_upsert)
        if merged != stories:
            fss["stories"] = merged
            base["fss"] = fss
            changed = True

    if not changed:
        return parent  # no-op

    fp = _sha256(_canonical(base))

    res = await db[WORKSPACE_ARTIFACTS].find_one_and_update(
        {"workspace_id": workspace_id},
        {
            "$set": {
                "inputs_baseline": base,
                "inputs_baseline_fingerprint": fp,
                "updated_at": datetime.utcnow(),
            },
            "$inc": {"inputs_baseline_version": 1},
        },
        return_document=ReturnDocument.AFTER,
    )
    return WorkspaceArtifactsDoc(**res)


# ─────────────────────────────────────────────────────────────
# Artifact queries
# (unchanged)
# ─────────────────────────────────────────────────────────────
async def _find_artifact_by_natural_key(
    db: AsyncIOMotorDatabase, workspace_id: str, natural_key: str
) -> Optional[ArtifactItem]:
    pipeline = [
        {"$match": {"workspace_id": workspace_id}},
        {"$unwind": "$artifacts"},
        {"$match": {"artifacts.natural_key": natural_key}},
        {"$replaceRoot": {"newRoot": "$artifacts"}},
        {"$limit": 1},
    ]
    cur = db[WORKSPACE_ARTIFACTS].aggregate(pipeline)
    doc = await cur.to_list(length=1)
    return ArtifactItem(**doc[0]) if doc else None


async def get_artifact(
    db: AsyncIOMotorDatabase, workspace_id: str, artifact_id: str
) -> Optional[ArtifactItem]:
    pipeline = [
        {"$match": {"workspace_id": workspace_id}},
        {"$unwind": "$artifacts"},
        {"$match": {"artifacts.artifact_id": artifact_id}},
        {"$replaceRoot": {"newRoot": "$artifacts"}},
        {"$limit": 1},
    ]
    cur = db[WORKSPACE_ARTIFACTS].aggregate(pipeline)
    doc = await cur.to_list(length=1)
    return ArtifactItem(**doc[0]) if doc else None


async def get_artifact_by_name(
    db: AsyncIOMotorDatabase, workspace_id: str, kind: str, name: str
) -> Optional[ArtifactItem]:
    pipeline = [
        {"$match": {"workspace_id": workspace_id}},
        {"$unwind": "$artifacts"},
        {"$match": {"artifacts.kind": kind, "artifacts.name": name}},
        {"$replaceRoot": {"newRoot": "$artifacts"}},
        {"$limit": 1},
    ]
    cur = db[WORKSPACE_ARTIFACTS].aggregate(pipeline)
    doc = await cur.to_list(length=1)
    return ArtifactItem(**doc[0]) if doc else None


async def list_artifacts(
    db: AsyncIOMotorDatabase,
    workspace_id: str,
    kind: Optional[str] = None,
    name_prefix: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    match_stage = {"$match": {"workspace_id": workspace_id}}
    pipeline = [match_stage, {"$unwind": "$artifacts"}]

    conds = []
    if not include_deleted:
        conds.append({"artifacts.deleted_at": None})
    if kind:
        conds.append({"artifacts.kind": kind})
    if name_prefix:
        conds.append({"artifacts.name": {"$regex": f"^{name_prefix}", "$options": "i"}})
    if conds:
        pipeline.append({"$match": {"$and": conds}})

    pipeline += [
        {"$sort": {"artifacts.updated_at": -1, "artifacts.artifact_id": 1}},
        {"$skip": max(0, offset)},
        {"$limit": min(limit, 200)},
        {"$replaceRoot": {"newRoot": "$artifacts"}},
    ]
    cur = db[WORKSPACE_ARTIFACTS].aggregate(pipeline)
    return [d async for d in cur]


# ─────────────────────────────────────────────────────────────
# Artifact writes (versioned upsert with lineage)
# ─────────────────────────────────────────────────────────────
async def upsert_artifact(
    db: AsyncIOMotorDatabase,
    workspace_id: str,
    payload: ArtifactItemCreate,
    prov: Optional[Provenance],
    *,
    run_id: Optional[str] = None,
) -> Tuple[ArtifactItem, str]:
    """
    Versioned, idempotent upsert by natural_key + data/diagram fingerprints.

    Returns: (artifact, op) where op ∈ {"insert","update","noop"}
    """
    now = datetime.utcnow()

    # Ensure parent exists
    parent = await get_parent_doc(db, workspace_id)
    if not parent:
        raise ValueError(f"Workspace parent not found for {workspace_id}")

    # Compute identity if caller didn't provide
    natural_key = payload.natural_key or _fallback_natural_key(payload.kind, payload.name)

    # Fingerprints
    data_fp = payload.fingerprint or _sha256(_canonical(payload.data))
    diagrams_norm = _normalize_diagrams(payload.diagrams)
    diagrams_fp = _sha256(_canonical(diagrams_norm)) if diagrams_norm else None

    # Lookup by NK
    existing = await _find_artifact_by_natural_key(db, workspace_id, natural_key)

    if existing is None:
        # Insert new artifact
        item = ArtifactItem(
            artifact_id=str(uuid.uuid4()),
            kind=payload.kind,
            name=payload.name,
            data=payload.data,
            diagrams=diagrams_norm,
            natural_key=natural_key,
            fingerprint=data_fp,
            diagram_fingerprint=diagrams_fp,
            version=1,
            lineage=Lineage(
                first_seen_run_id=run_id, last_seen_run_id=run_id, supersedes=[], superseded_by=None
            ),
            created_at=now,
            updated_at=now,
            provenance=prov,
        )
        res = await db[WORKSPACE_ARTIFACTS].update_one(
            {"workspace_id": workspace_id},
            {"$push": {"artifacts": item.model_dump()}, "$set": {"updated_at": now}},
        )
        if res.matched_count == 0:
            raise ValueError(f"Workspace parent not found for {workspace_id}")
        return item, "insert"

    # Compare existing content
    existing_data_fp = existing.fingerprint
    existing_diag_fp = getattr(existing, "diagram_fingerprint", None)

    data_changed = (existing_data_fp != data_fp)
    diagrams_changed = (diagrams_fp is not None and diagrams_fp != existing_diag_fp) or \
                       (diagrams_fp is None and existing_diag_fp is not None and diagrams_norm == [])

    if not data_changed and not diagrams_changed:
        # No changes → just touch lineage/updated_at
        res = await db[WORKSPACE_ARTIFACTS].find_one_and_update(
            {
                "workspace_id": workspace_id,
                "artifacts.natural_key": natural_key,
                "artifacts.deleted_at": None,
            },
            {
                "$set": {
                    "artifacts.$.lineage.last_seen_run_id": run_id,
                    "artifacts.$.updated_at": now,
                    "updated_at": now,
                }
            },
            return_document=ReturnDocument.AFTER,
            projection={"artifacts": 1, "_id": 0},
        )
        a = next((x for x in res["artifacts"] if x.get("natural_key") == natural_key), None)
        return ArtifactItem(**a), "noop"

    # Prepare update
    set_fields: Dict[str, Any] = {
        "artifacts.$.lineage.last_seen_run_id": run_id,
        "artifacts.$.updated_at": now,
        "updated_at": now,
    }
    if data_changed:
        set_fields["artifacts.$.data"] = payload.data
        set_fields["artifacts.$.fingerprint"] = data_fp
    if diagrams_changed:
        set_fields["artifacts.$.diagrams"] = diagrams_norm
        set_fields["artifacts.$.diagram_fingerprint"] = diagrams_fp

    res = await db[WORKSPACE_ARTIFACTS].find_one_and_update(
        {
            "workspace_id": workspace_id,
            "artifacts.natural_key": natural_key,
            "artifacts.deleted_at": None,
        },
        {
            "$set": set_fields,
            "$inc": {"artifacts.$.version": 1},
        },
        return_document=ReturnDocument.AFTER,
        projection={"artifacts": 1, "_id": 0},
    )
    if not res:
        raise ValueError("Artifact to update not found")

    a = next((x for x in res["artifacts"] if x.get("natural_key") == natural_key), None)
    return ArtifactItem(**a), "update"


async def replace_artifact(
    db: AsyncIOMotorDatabase,
    workspace_id: str,
    artifact_id: str,
    new_data: Optional[Dict[str, Any]],
    prov: Optional[Provenance],
    new_diagrams: Optional[List[DiagramInstance]] = None,
) -> ArtifactItem:
    now = datetime.utcnow()

    # Compute new fingerprints
    set_fields: Dict[str, Any] = {
        "artifacts.$[a].updated_at": now,
        "updated_at": now,
        "artifacts.$[a].provenance": (prov.model_dump() if prov else None),
    }
    if new_data is not None:
        set_fields["artifacts.$[a].data"] = new_data
        set_fields["artifacts.$[a].fingerprint"] = _sha256(_canonical(new_data))
    if new_diagrams is not None:
        diagrams_norm = _normalize_diagrams(new_diagrams)
        set_fields["artifacts.$[a].diagrams"] = diagrams_norm
        set_fields["artifacts.$[a].diagram_fingerprint"] = _sha256(_canonical(diagrams_norm)) if diagrams_norm else None

    res = await db[WORKSPACE_ARTIFACTS].find_one_and_update(
        {"workspace_id": workspace_id},
        {
            "$set": set_fields,
            "$inc": {"artifacts.$[a].version": 1},
        },
        array_filters=[{"a.artifact_id": artifact_id}],
        return_document=ReturnDocument.AFTER,
        projection={"artifacts": 1, "_id": 0},
    )
    if not res:
        raise ValueError("Artifact or workspace not found")
    for a in res["artifacts"]:
        if a.get("artifact_id") == artifact_id:
            return ArtifactItem(**a)
    raise ValueError("Updated artifact not found after replace")


async def soft_delete_artifact(
    db: AsyncIOMotorDatabase, workspace_id: str, artifact_id: str
) -> Optional[ArtifactItem]:
    now = datetime.utcnow()
    res = await db[WORKSPACE_ARTIFACTS].find_one_and_update(
        {"workspace_id": workspace_id},
        {
            "$set": {
                "artifacts.$[a].deleted_at": now,
                "artifacts.$[a].updated_at": now,
                "updated_at": now,
            }
        },
        array_filters=[{"a.artifact_id": artifact_id, "a.deleted_at": None}],
        return_document=ReturnDocument.AFTER,
        projection={"artifacts": 1, "_id": 0},
    )
    if not res:
        return None
    for a in res["artifacts"]:
        if a.get("artifact_id") == artifact_id:
            return ArtifactItem(**a)
    return None


# ─────────────────────────────────────────────────────────────
# Patch history (unchanged)
# ─────────────────────────────────────────────────────────────
async def record_patch(
    db: AsyncIOMotorDatabase,
    workspace_id: str,
    artifact_id: str,
    from_version: int,
    to_version: int,
    patch: List[Dict[str, Any]],
    prov: Optional[Provenance],
):
    doc = {
        "_id": str(uuid.uuid4()),
        "artifact_id": artifact_id,
        "workspace_id": workspace_id,
        "from_version": from_version,
        "to_version": to_version,
        "patch": patch,
        "created_at": datetime.utcnow(),
        "provenance": prov.model_dump() if prov else None,
    }
    await db[PATCHES].insert_one(doc)


async def list_patches(
    db: AsyncIOMotorDatabase, workspace_id: str, artifact_id: str
) -> List[Dict[str, Any]]:
    cur = db[PATCHES].find({"workspace_id": workspace_id, "artifact_id": artifact_id}).sort("to_version", 1)
    return [d async for d in cur]


# ─────────────────────────────────────────────────────────────
# Run delta computation (unchanged)
# ─────────────────────────────────────────────────────────────
def _prov_run_id(prov: Optional[Provenance | Dict[str, Any]]) -> Optional[str]:
    if prov is None:
        return None
    if hasattr(prov, "run_id"):
        try:
            return getattr(prov, "run_id")
        except Exception:
            pass
    if isinstance(prov, dict):
        return prov.get("run_id")
    return None


def compute_run_deltas(
    parent: WorkspaceArtifactsDoc,
    *,
    run_id: str,
    include_ids: bool = False,
) -> Dict[str, Any]:
    buckets = {
        "new": [],
        "updated": [],
        "unchanged": [],
        "retired": [],
        "deleted": [],
    }

    for a in parent.artifacts:
        if getattr(a, "deleted_at", None) is not None:
            buckets["deleted"].append(a.artifact_id)
            continue

        first_seen = getattr(a.lineage, "first_seen_run_id", None) if a.lineage else None
        last_seen = getattr(a.lineage, "last_seen_run_id", None) if a.lineage else None
        prov_run = _prov_run_id(a.provenance)

        if first_seen == run_id:
            buckets["new"].append(a.artifact_id)
        elif prov_run == run_id:
            buckets["updated"].append(a.artifact_id)
        elif last_seen == run_id:
            buckets["unchanged"].append(a.artifact_id)
        else:
            buckets["retired"].append(a.artifact_id)

    counts = {k: len(v) for k, v in buckets.items()}
    out: Dict[str, Any] = {"counts": counts}
    if include_ids:
        out["ids"] = buckets
    return out
