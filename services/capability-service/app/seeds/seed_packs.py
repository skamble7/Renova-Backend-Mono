from __future__ import annotations

import logging
import os

from app.models import CapabilityPackCreate, Playbook, PlaybookStep
from app.services import PackService

log = logging.getLogger("app.seeds.packs")


async def _delete_pack_if_exists(svc: PackService, key: str, version: str) -> None:
    """
    Best-effort delete for an existing pack identified by key+version.
    Works with common method names and guards for environments where delete
    may not be available.
    """
    try:
        existing = await svc.get_by_key_version(key, version)
    except Exception:
        existing = None

    if not existing:
        return

    # Try typical delete signatures
    for meth_name in ("delete", "remove", "archive"):
        m = getattr(svc, meth_name, None)
        if callable(m):
            try:
                # Some services accept "key@version", others accept an id, others accept key+version args.
                try:
                    await m(f"{key}@{version}", actor="seed")  # e.g., delete("key@version")
                    log.info("[capability.seeds.packs] %s('%s@%s') ok", meth_name, key, version)
                    return
                except TypeError:
                    try:
                        await m(existing.id, actor="seed")  # e.g., delete(doc_id)
                        log.info("[capability.seeds.packs] %s(id=%s) ok", meth_name, existing.id)
                        return
                    except TypeError:
                        await m(key, version, actor="seed")  # e.g., delete(key, version)
                        log.info("[capability.seeds.packs] %s('%s','%s') ok", meth_name, key, version)
                        return
            except Exception as e:
                log.warning("[capability.seeds.packs] %s failed: %s", meth_name, e)

    log.warning("[capability.seeds.packs] Could not delete existing pack %s@%s; continuing with create()", key, version)


async def _create_refresh_publish(svc: PackService, payload: CapabilityPackCreate, publish_on_seed: bool) -> None:
    """
    Helper to create, refresh snapshots, and optionally publish a pack.
    Assumes the caller has already cleaned up any existing same-version pack if desired.
    """
    key = payload.key
    version = payload.version

    created = await svc.create(payload, actor="seed")
    log.info("[capability.seeds.packs] created: %s@%s (id=%s)", key, version, getattr(created, "id", None))

    refreshed = await svc.refresh_snapshots(f"{key}@{version}")
    if refreshed:
        log.info("[capability.seeds.packs] snapshots refreshed: %s", refreshed.id)
    else:
        log.warning("[capability.seeds.packs] pack not found for snapshot refresh: %s@%s", key, version)
        return

    if publish_on_seed:
        published = await svc.publish(f"{key}@{version}", actor="seed")
        if published:
            log.info("[capability.seeds.packs] published: %s", published.id)
        else:
            log.warning("[capability.seeds.packs] publish failed or pack not found for %s@%s", key, version)
    else:
        log.info("[capability.seeds.packs] publish skipped via env for %s@%s", key, version)


async def seed_packs() -> None:
    """
    Seed TWO capability packs under the same key 'cobol-mainframe':
      1) v1.0.1 (existing full-flow pack) — preserved as-is.
      2) v1.0.2 (new minimal pack) — two-step playbook: cap.repo.clone -> cap.cobol.parse.

    If PACK_SEED_PUBLISH=1, both will be published after snapshot refresh.
    """
    log.info("[capability.seeds.packs] Begin")

    publish_on_seed = os.getenv("PACK_SEED_PUBLISH", "1") in ("1", "true", "True")
    svc = PackService()

    pack_key = "cobol-mainframe"
    full_version = "v1.0.1"   # existing full pack (unchanged)
    mini_version = "v1.0.2"   # new derived minimal pack

    # -------------------------------
    # Pack #1: Full-flow v1.0.1 (UNCHANGED)
    # -------------------------------
    # Do NOT delete v1.0.1 unless we're re-seeding the exact same version for idempotency.
    # We only remove the same version if present to allow updates in a controlled re-run.
    await _delete_pack_if_exists(svc, pack_key, full_version)

    pb_main = Playbook(
        id="pb.main",
        name="Main COBOL Learning Flow",
        description="Topologically ordered steps to parse, index, enrich, and render the enterprise flow.",
        steps=[
            PlaybookStep(
                id="s1.clone",
                name="Clone Repo",
                capability_id="cap.repo.clone",
                description="Clone source repository; records commit and paths_root.",
                params={"url": "${git.url}", "branch": "${git.branch:-main}", "depth": 0, "dest": "${repo.dest:-/mnt/src}"},
            ),
            PlaybookStep(
                id="s2.cobol",
                name="Parse COBOL",
                capability_id="cap.cobol.parse",
                description="ProLeap/cb2xml parse of programs and copybooks into normalized CAM kinds.",
                params={"root": "${repo.paths_root}", "paths": [], "dialect": "COBOL85"},
            ),
            PlaybookStep(
                id="s3.jcl",
                name="Parse JCL",
                capability_id="cap.jcl.parse",
                description="Parse JCL jobs/steps and DDs.",
                params={"root": "${repo.paths_root}", "paths": []},
            ),
            PlaybookStep(
                id="s4.cics",
                name="Discover CICS (optional)",
                capability_id="cap.cics.catalog",
                description="If configured, discover transaction→program mapping.",
                params={"region": "${cics.region}", "filter": "${cics.filter:-*}"},
            ),
            PlaybookStep(
                id="s5.db2",
                name="Export DB2 Catalog (optional)",
                capability_id="cap.db2.catalog",
                description="Load DB2 schema via connection alias or DDL folder.",
                params={"conn_alias": "${db2.conn_alias}", "schemas": ["${db2.schema:-*}"], "ddl_root": "${db2.ddl_root}"},
            ),
            PlaybookStep(
                id="s6.graph",
                name="Index Enterprise Graph",
                capability_id="cap.graph.index",
                description="Build service/dependency inventories from parsed facts.",
                params={"resolve_dynamic_calls": False, "max_depth": 5},
            ),
            PlaybookStep(
                id="s7.entities",
                name="Detect Entities & Terms",
                capability_id="cap.entity.detect",
                description="Lift copybooks/physical into logical data model and domain dictionary.",
                params={"naming_style": "title", "merge_similar_threshold": 0.85},
            ),
            PlaybookStep(
                id="s8.lineage",
                name="Derive Data Lineage",
                capability_id="cap.lineage.derive",
                description="Conservative field-level lineage from IO ops and steps.",
                params={"include_transforms": True},
            ),
            PlaybookStep(
                id="s9.batch",
                name="Mine Batch Workflows",
                capability_id="cap.workflow.mine_batch",
                description="Deterministic stitching of job flows + call graph.",
                params={"lane_by": "job"},
            ),
            PlaybookStep(
                id="s10.entity",
                name="Mine Entity Workflows",
                capability_id="cap.workflow.mine_entity",
                description="Entity-centric slicing and business-readable flows.",
                params={"entity_names": ["Account", "Customer", "Transaction"], "max_hops": 5},
            ),
            PlaybookStep(
                id="s11.diagrams",
                name="Render Diagrams",
                capability_id="cap.diagram.render",
                description="Render activity/sequence/component/deployment/state diagrams.",
                params={"targets": ["activity", "sequence", "component", "deployment", "state"]},
            ),
        ],
    )

    payload_full = CapabilityPackCreate(
        key=pack_key,
        version=full_version,
        title="COBOL Mainframe Modernization",
        description="Deterministic MCP parsing + LLM enrichment to discover inventories, data lineage, and workflows from COBOL/JCL estates.",
        capability_ids=[
            "cap.repo.clone",
            "cap.cobol.parse",
            "cap.jcl.parse",
            "cap.cics.catalog",
            "cap.db2.catalog",
            "cap.graph.index",
            "cap.entity.detect",
            "cap.lineage.derive",
            "cap.workflow.mine_batch",
            "cap.workflow.mine_entity",
            "cap.diagram.render",
        ],
        playbooks=[pb_main],
    )

    await _create_refresh_publish(svc, payload_full, publish_on_seed)

    # -------------------------------
    # Pack #2: Minimal two-step v1.0.2 (NEW)
    # -------------------------------
    # Only delete same-version (v1.0.2) for idempotent reseeding; DO NOT touch v1.0.1.
    await _delete_pack_if_exists(svc, pack_key, mini_version)

    pb_core = Playbook(
        id="pb.core",
        name="Core Clone + Parse",
        description="Minimal flow to clone a repo and parse COBOL sources.",
        steps=[
            PlaybookStep(
                id="s1.clone",
                name="Clone Repo",
                capability_id="cap.repo.clone",
                description="Clone source repository; records commit and paths_root.",
                params={"url": "${git.url}", "branch": "${git.branch:-main}", "depth": 0, "dest": "${repo.dest:-/mnt/src}"},
            ),
            PlaybookStep(
                id="s2.cobol",
                name="Parse COBOL",
                capability_id="cap.cobol.parse",
                description="ProLeap/cb2xml parse of programs and copybooks into normalized CAM kinds.",
                params={"root": "${repo.paths_root}", "paths": [], "dialect": "COBOL85"},
            ),
        ],
    )

    payload_mini = CapabilityPackCreate(
        key=pack_key,
        version=mini_version,
        title="COBOL Mainframe Modernization (Core)",
        description="Derived minimal pack with a two-step playbook: clone repo then parse COBOL.",
        capability_ids=[
            "cap.repo.clone",
            "cap.cobol.parse",
        ],
        playbooks=[pb_core],
    )

    await _create_refresh_publish(svc, payload_mini, publish_on_seed)

    log.info("[capability.seeds.packs] Done (seeded %s@%s and %s@%s)", pack_key, full_version, pack_key, mini_version)
