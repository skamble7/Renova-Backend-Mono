from __future__ import annotations

import logging
import os
import uuid

from app.models import CapabilityPackCreate, Playbook, PlaybookStep
from app.services import PackService, CapabilityService

log = logging.getLogger("app.seeds.packs")


async def seed_packs() -> None:
    """
    Seed a draft 'cobol-mainframe' pack with a simple playbook.
    If PACK_SEED_PUBLISH=1, will publish after snapshot refresh.
    """
    log.info("[capability.seeds.packs] Begin")

    publish_on_seed = os.getenv("PACK_SEED_PUBLISH", "1") in ("1", "true", "True")

    pack_key = "cobol-mainframe"
    pack_version = "v1.0"

    # Referenced capability ids
    capability_ids = [
        "cap.cobol.copybook.parse",
        "cap.jcl.job.catalog",
        "cap.cobol.callgraph.build",
        "cap.domain.dictionary.extract",
        "cap.workflow.batch_map",
    ]

    # Simple playbook (order mirrors a natural flow; learning-service will handle deps)
    pb = Playbook(
        id="pb.main",
        name="Main COBOL Learning Flow",
        description="Deterministic parsing → graph → LLM enrichment",
        steps=[
            PlaybookStep(
                id="s1",
                name="Parse Copybooks",
                capability_id="cap.cobol.copybook.parse",
                params={},
            ),
            PlaybookStep(
                id="s2",
                name="Catalog JCL Jobs",
                capability_id="cap.jcl.job.catalog",
                params={},
            ),
            PlaybookStep(
                id="s3",
                name="Build COBOL Call Graph",
                capability_id="cap.cobol.callgraph.build",
                params={},
            ),
            PlaybookStep(
                id="s4",
                name="Extract Domain Dictionary",
                capability_id="cap.domain.dictionary.extract",
                params={"strategy": "extractive+fewshot"},
            ),
            PlaybookStep(
                id="s5",
                name="Assemble Batch Workflow Map",
                capability_id="cap.workflow.batch_map",
                params={"include_timing": False},
            ),
        ],
    )

    svc = PackService()
    cap_svc = CapabilityService()

    # If pack exists, skip create but do refresh/publish branch
    exists = await svc.get_by_key_version(pack_key, pack_version)
    if not exists:
        payload = CapabilityPackCreate(
            key=pack_key,
            version=pack_version,
            title="COBOL Mainframe Capability Pack",
            description="Deterministic MCP parsing plus LLM enrichment for mainframe modernization.",
            capability_ids=capability_ids,
            playbooks=[pb],
        )
        created = await svc.create(payload, actor="seed")
        log.info("[capability.seeds.packs] created: %s@%s", pack_key, pack_version)
    else:
        log.info("[capability.seeds.packs] exists: %s@%s", pack_key, pack_version)

    # (Re)build snapshots from current capability docs
    refreshed = await svc.refresh_snapshots(f"{pack_key}@{pack_version}")
    if refreshed:
        log.info("[capability.seeds.packs] snapshots refreshed: %s", refreshed.id)
    else:
        log.warning("[capability.seeds.packs] pack not found for snapshot refresh")
        return

    # Optional publish
    if publish_on_seed:
        published = await svc.publish(f"{pack_key}@{pack_version}", actor="seed")
        if published:
            log.info("[capability.seeds.packs] published: %s", published.id)
        else:
            log.warning("[capability.seeds.packs] publish failed or pack not found")
    else:
        log.info("[capability.seeds.packs] publish skipped via env")

    log.info("[capability.seeds.packs] Done")
