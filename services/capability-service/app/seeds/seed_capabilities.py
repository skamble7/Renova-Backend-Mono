from __future__ import annotations

import logging

from app.models import (
    GlobalCapabilityCreate,
    MCPIntegrationBinding,
    MCPToolCallSpec,
    LLMConfig,
)
from app.services import CapabilityService

log = logging.getLogger("app.seeds.capabilities")


async def seed_capabilities() -> None:
    """
    Seed a starter set of capabilities:
      - MCP-driven (deterministic): copybook parse, jcl catalog, callgraph build
      - LLM-driven: domain dictionary extraction, batch workflow mapping
    """
    log.info("[capability.seeds] Begin")

    svc = CapabilityService()

    targets: list[GlobalCapabilityCreate] = [
        GlobalCapabilityCreate(
            id="cap.cobol.copybook.parse",
            name="Parse COBOL Copybooks",
            description="Extracts field layouts and data types from copybooks.",
            tags=["cobol", "copybook"],
            produces_kinds=["cam.cobol.copybook"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.cobol.parser",
                tool_calls=[MCPToolCallSpec(tool="parse_copybooks", output_kinds=["cam.cobol.copybook"])],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.jcl.job.catalog",
            name="Catalog JCL Jobs",
            description="Parses JCL members to produce normalized job descriptors.",
            tags=["cobol", "jcl"],
            produces_kinds=["cam.cobol.jcl_job"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.jcl.parser",
                tool_calls=[MCPToolCallSpec(tool="parse_jcl_jobs", output_kinds=["cam.cobol.jcl_job"])],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.cobol.callgraph.build",
            name="Build COBOL Call Graph",
            description="Computes inter-program call relationships.",
            tags=["cobol", "graph"],
            produces_kinds=["cam.legacy.call_graph"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.cobol.callgraph",
                tool_calls=[MCPToolCallSpec(tool="build_callgraph", output_kinds=["cam.legacy.call_graph"])],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.domain.dictionary.extract",
            name="Extract Domain Dictionary",
            description="LLM-based extraction of ubiquitous language from code/comments.",
            tags=["domain", "semantics"],
            produces_kinds=["cam.domain.dictionary"],
            llm_config=LLMConfig(
                provider="openai",
                model="gpt-4.1-mini",
                parameters={"temperature": 0, "response_format": "json_object"},
                output_contracts={"cam.domain.dictionary": "1.0.0"},
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.workflow.batch_map",
            name="Assemble Batch Workflow Map",
            description="LLM stitches JCL jobs into batch workflows and dependencies.",
            tags=["workflow", "batch"],
            produces_kinds=["cam.workflow.batch_job"],
            llm_config=LLMConfig(
                provider="openai",
                model="gpt-4.1-mini",
                parameters={"temperature": 0},
                output_contracts={"cam.workflow.batch_job": "1.0.0"},
            ),
        ),
    ]

    created = 0
    for cap in targets:
        existing = await svc.get(cap.id)
        if existing:
            log.info("[capability.seeds] exists: %s", cap.id)
            continue
        await svc.create(cap, actor="seed")
        log.info("[capability.seeds] created: %s", cap.id)
        created += 1

    if created == 0:
        log.info("[capability.seeds] Skipped (collection already has records)")
    else:
        log.info("[capability.seeds] Done (created=%d)", created)
