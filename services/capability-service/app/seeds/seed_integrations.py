from __future__ import annotations

import logging
import os

from app.models import MCPIntegration, IntegrationAuthRef
from app.services import IntegrationService

log = logging.getLogger("app.seeds.integrations")


async def seed_integrations() -> None:
    """
    Create a few reusable MCP integrations for COBOL/JCL parsing & callgraph.
    Endpoints can be overridden via env vars below.
    """
    log.info("[capability.seeds.integrations] Begin")

    cobol_parser_ep = os.getenv("COBOL_PARSER_ENDPOINT", "http://host.docker.internal:7101")
    jcl_parser_ep = os.getenv("JCL_PARSER_ENDPOINT", "http://host.docker.internal:7102")
    callgraph_ep = os.getenv("CALLGRAPH_ENDPOINT", "http://host.docker.internal:7103")

    svc = IntegrationService()

    targets = [
        MCPIntegration(
            id="mcp.cobol.parser",
            name="COBOL Copybook Parser MCP",
            description="Parses COBOL copybooks and emits normalized structures.",
            tags=["cobol", "parser"],
            type="mcp",
            endpoint=cobol_parser_ep,
            protocol="http",
            auth=IntegrationAuthRef(method="none"),
        ),
        MCPIntegration(
            id="mcp.jcl.parser",
            name="JCL Parser MCP",
            description="Parses JCL members/jobs and produces job specs.",
            tags=["cobol", "jcl", "parser"],
            type="mcp",
            endpoint=jcl_parser_ep,
            protocol="http",
            auth=IntegrationAuthRef(method="none"),
        ),
        MCPIntegration(
            id="mcp.cobol.callgraph",
            name="COBOL Callgraph MCP",
            description="Builds a call graph across COBOL programs using copybooks & sources.",
            tags=["cobol", "graph"],
            type="mcp",
            endpoint=callgraph_ep,
            protocol="http",
            auth=IntegrationAuthRef(method="none"),
        ),
    ]

    created = 0
    for integ in targets:
        existing = await svc.get(integ.id)
        if existing:
            log.info("[capability.seeds.integrations] exists: %s", integ.id)
            continue
        await svc.create(integ, actor="seed")
        log.info("[capability.seeds.integrations] created: %s -> %s", integ.id, integ.endpoint)
        created += 1

    if created == 0:
        log.info("[capability.seeds.integrations] Skipped (collection already has records)")
    else:
        log.info("[capability.seeds.integrations] Done (created=%d)", created)
