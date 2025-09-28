from __future__ import annotations

import logging
import inspect

from app.models import (
    GlobalCapabilityCreate,
    MCPIntegrationBinding,
    MCPToolCallSpec,
    LLMConfig,
)
from app.services import CapabilityService

log = logging.getLogger("app.seeds.capabilities")


async def _try_wipe_all(svc: CapabilityService) -> bool:
    """
    Best-effort collection wipe without relying on list_all().
    Tries common method names; returns True if any succeeded.
    """
    candidates = [
        "delete_all", "purge_all", "purge", "truncate", "clear",
        "reset", "drop_all", "wipe_all"
    ]
    for name in candidates:
        method = getattr(svc, name, None)
        if callable(method):
            try:
                result = method()
                if inspect.isawaitable(result):
                    await result
                log.info("[capability.seeds] wiped existing via CapabilityService.%s()", name)
                return True
            except Exception as e:
                log.warning("[capability.seeds] %s() failed: %s", name, e)
    return False


async def seed_capabilities() -> None:
    """
    Seeds ONLY the new capability set (correct ID format).
    Steps:
      1) Try to wipe all existing capabilities using any available service method.
      2) Replace-by-id for each new capability (delete-if-exists → create).

    NOTE: MCPToolCallSpec.timeout_sec must be an int ≤ 3600 (per model constraints).
    """
    log.info("[capability.seeds] Begin")

    svc = CapabilityService()

    # 1) Try full wipe (no references to old IDs)
    wiped = await _try_wipe_all(svc)
    if not wiped:
        log.info("[capability.seeds] No wipe method found; proceeding with replace-by-id for targets")

    LONG_TIMEOUT = 3600  # model-enforced maximum

    # 2) New targets
    targets: list[GlobalCapabilityCreate] = [
        GlobalCapabilityCreate(
            id="cap.repo.clone",
            name="Clone Source Repository",
            description="Clones the source repository and records commit and root path information.",
            produces_kinds=["cam.asset.repo_snapshot"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.git",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="clone_repo",
                        output_kinds=["cam.asset.repo_snapshot"],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.source.index",
            name="Index Source Files",
            description="Indexes source files and detects type/kind (COBOL, JCL, copybook, etc.).",
            produces_kinds=["cam.asset.source_file"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.source.indexer",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="index_sources",
                        output_kinds=["cam.asset.source_file"],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.cobol.parse",
            name="Parse COBOL Programs and Copybooks",
            description="Parses COBOL source files and extracts program and copybook structures.",
            produces_kinds=["cam.cobol.program","cam.asset.source_index","cam.cobol.copybook"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.cobol.parser",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="parse_tree",
                        output_kinds=["cam.cobol.program", "cam.asset.source_index","cam.cobol.copybook"],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.jcl.parse",
            name="Parse JCL Jobs and Steps",
            description="Parses JCL jobs and steps including datasets and program calls.",
            produces_kinds=["cam.jcl.job", "cam.jcl.step"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.jcl.parser",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="parse_jcl",
                        output_kinds=["cam.jcl.job", "cam.jcl.step"],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.cics.catalog",
            name="Discover CICS Transactions",
            description="Discovers CICS transactions and maps them to COBOL programs.",
            produces_kinds=["cam.cics.transaction"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.cics.catalog",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="list_transactions",
                        output_kinds=["cam.cics.transaction"],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.db2.catalog",
            name="Export DB2 Catalog",
            description="Exports DB2 schemas and tables either via connection or DDL scan.",
            produces_kinds=["cam.data.model"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.db2.catalog",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="export_schema",
                        output_kinds=["cam.data.model"],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.graph.index",
            name="Index Enterprise Graph",
            description="Builds inventories and dependency graphs from parsed COBOL, JCL, and DB2 facts.",
            produces_kinds=["cam.asset.service_inventory", "cam.asset.dependency_inventory"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.graph.indexer",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="index",
                        output_kinds=["cam.asset.service_inventory", "cam.asset.dependency_inventory"],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.entity.detect",
            name="Detect Entities and Business Terms",
            description="Lifts copybooks and DB2 schemas into logical entities and extracts a domain dictionary.",
            produces_kinds=["cam.data.model", "cam.domain.dictionary"],
            llm_config=LLMConfig(
                provider="openai",
                model="gpt-4.1",
                parameters={"temperature": 0, "json_mode": True, "max_tokens": 2000},
                output_contracts={
                    "cam.data.model": "1.0.0",
                    "cam.domain.dictionary": "1.0.0",
                },
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.lineage.derive",
            name="Derive Data Lineage",
            description="Derives data lineage across programs, jobs, and entities.",
            produces_kinds=["cam.data.lineage"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.lineage.engine",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="derive_lineage",
                        output_kinds=["cam.data.lineage"],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.workflow.mine_batch",
            name="Mine Batch Workflows",
            description="Mines batch workflows from JCL job flows and COBOL call graphs.",
            produces_kinds=["cam.workflow.process"],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.workflow.miner",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="mine_batch",
                        output_kinds=["cam.workflow.process"],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.workflow.mine_entity",
            name="Mine Entity Workflows",
            description="Discovers entity-centric workflows such as Account or Customer lifecycle.",
            produces_kinds=["cam.workflow.process"],
            llm_config=LLMConfig(
                provider="openai",
                model="gpt-4.1",
                parameters={"temperature": 0, "json_mode": True, "max_tokens": 2000},
                output_contracts={"cam.workflow.process": "1.0.0"},
            ),
        ),
        GlobalCapabilityCreate(
            id="cap.diagram.render",
            name="Render Diagrams",
            description="Renders activity, sequence, component, deployment, and state diagrams from workflow and inventories.",
            produces_kinds=[
                "cam.diagram.activity",
                "cam.diagram.sequence",
                "cam.diagram.component",
                "cam.diagram.deployment",
                "cam.diagram.state",
            ],
            integration=MCPIntegrationBinding(
                integration_ref="mcp.diagram.exporter",
                tool_calls=[
                    MCPToolCallSpec(
                        tool="render_diagrams",
                        output_kinds=[
                            "cam.diagram.activity",
                            "cam.diagram.sequence",
                            "cam.diagram.component",
                            "cam.diagram.deployment",
                            "cam.diagram.state",
                        ],
                        timeout_sec=LONG_TIMEOUT,
                        retries=1,
                    )
                ],
            ),
        ),
    ]

    # Replace-by-id creation (no mention of legacy IDs)
    created = 0
    for cap in targets:
        try:
            existing = await svc.get(cap.id)
            if existing:
                try:
                    await svc.delete(cap.id, actor="seed")
                    log.info("[capability.seeds] replaced: %s (deleted old)", cap.id)
                except AttributeError:
                    log.warning("[capability.seeds] delete() not available; attempting create() which may fail on unique ID")
        except Exception:
            # get() not found -> OK
            pass

        await svc.create(cap, actor="seed")
        log.info("[capability.seeds] created: %s", cap.id)
        created += 1

    log.info("[capability.seeds] Done (created=%d)", created)
