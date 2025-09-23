# services/capability-service/app/seeds/seed_integrations.py
from __future__ import annotations

import logging

from app.models import MCPIntegration, StdioTransport, HTTPTransport
from app.services import IntegrationService

log = logging.getLogger("app.seeds.integrations")


def _transport_str(t) -> str:
    """Human-friendly transport description for logs."""
    try:
        if isinstance(t, StdioTransport):
            return f"stdio cmd='{t.command}' cwd='{t.cwd or ''}'"
        if isinstance(t, HTTPTransport):
            return f"http base_url='{t.base_url}'"
    except Exception:
        pass
    kind = getattr(t, "kind", "unknown")
    return f"{kind}"


async def seed_integrations() -> None:
    """
    Reseat integrations to the transport-based MCPIntegration shape.

    Notes:
    - mcp.git and mcp.cobol.parser are launched via `docker run` with the
      project root mounted at /mnt/work inside the tool containers.
    - We DO NOT wait for a readiness banner (readiness_regex=None) because the
      containers don’t emit a stable line. The STDIO bridge will be ready to
      receive tool calls immediately.
    """
    log.info("[capability.seeds.integrations] Begin")
    svc = IntegrationService()

    # 1) Best-effort delete to avoid unique-key conflicts
    delete_ids = [
        "mcp.git",
        "mcp.cobol.parser",
        "mcp.jcl.parser",
        "mcp.cics.catalog",
        "mcp.db2.catalog",
        "mcp.dataset.scanner",
        "mcp.graph.indexer",
        "mcp.lineage.engine",
        "mcp.workflow.miner",
        "mcp.diagram.exporter",
        "mcp.cobol.callgraph",  # legacy
    ]
    for oid in delete_ids:
        try:
            if await svc.get(oid):
                try:
                    await svc.delete(oid, actor="seed")
                    log.info("[capability.seeds.integrations] deleted existing: %s", oid)
                except AttributeError:
                    log.warning("[capability.seeds.integrations] delete() not available; could not remove %s", oid)
        except Exception:
            pass

    # 2) Define integrations
    targets = [
        # ----- mcp.git via docker run (stdio) -----
        MCPIntegration(
            id="mcp.git",
            name="Git MCP",
            description="Clone and inspect Git repositories for learning runs.",
            tags=["repo", "git", "source"],
            transport=StdioTransport(
                kind="stdio",
                command="docker",
                args=[
                    "run",
                    "--rm",
                    "-i",
                    "-v", "${workspaceFolder}:/mnt/work",
                    "-w", "/opt/renova/tools/git",
                    "-e", "LOG_LEVEL=info",
                    "-e", "REPO_WORK_ROOT=/mnt/work/.renova/src",
                    "-e", "REPO_CACHE=/mnt/work/.renova/cache",
                    "-e", "GIT_ALLOWED_HOSTS=github.com,git.example.com",
                    "-e", "GIT_DISABLE_REFERENCE=1",
                    "git-mcp:dev",
                    "--stdio",
                ],
                # Launch docker from the repo root (safer if you later use relative paths)
                cwd="${workspaceFolder}",
                env={},            # everything the tool needs is passed into the container via -e above
                env_aliases={},
                restart_on_exit=True,
                readiness_regex=None,  # <— do not wait for a banner; start immediately
                kill_timeout_sec=10,
            ),
        ),

        # ----- mcp.cobol.parser via docker run (stdio) -----
        MCPIntegration(
            id="mcp.cobol.parser",
            name="COBOL Parser MCP",
            description="ProLeap/cb2xml-backed parser emitting normalized COBOL facts.",
            tags=["cobol", "parse", "proleap"],
            transport=StdioTransport(
                kind="stdio",
                command="docker",
                args=[
                    "run",
                    "--rm",
                    "-i",
                    "-v", "${workspaceFolder}:/mnt/work",
                    "-w", "/opt/renova/tools/cobol-parser",
                    "-e", "LOG_LEVEL=info",
                    "-e", "COBOL_DIALECT=COBOL85",
                    "-e", "WORKSPACE_HOST=${workspaceFolder}",
                    "-e", "WORKSPACE_CONTAINER=/mnt/work",
                    # cb2xml (optional)
                    "-e", "CB2XML_CLASSPATH=/opt/cb2xml/lib/*",
                    "-e", "CB2XML_MAIN=net.sf.cb2xml.Cb2Xml",
                    # ProLeap bridge
                    "-e", "PROLEAP_CLASSPATH=/opt/proleap/lib/proleap-cli-bridge.jar",
                    "-e", "PROLEAP_MAIN=com.renova.proleap.CLI",
                    # debug dumps
                    "-e", "RAW_AST_DUMP_DIR=/mnt/work/.renova/debug/raw-ast",
                    "cobol-parser-mcp:dev",
                ],
                cwd="${workspaceFolder}",
                env={},
                env_aliases={},
                restart_on_exit=True,
                readiness_regex=None,  # <— do not wait for a banner to avoid startup timeout
                kill_timeout_sec=10,
            ),
        ),

        # ----- everything else unchanged -----
        MCPIntegration(
            id="mcp.jcl.parser",
            name="JCL Parser MCP",
            description="Parses JCL jobs/steps and DD statements.",
            tags=["jcl", "batch"],
            transport=StdioTransport(
                kind="stdio",
                command="jcl-parser-mcp",
                args=["--stdio"],
                cwd="/opt/renova/tools/jcl-parser",
                env={"LOG_LEVEL": "info"},
                env_aliases={},
                restart_on_exit=True,
                readiness_regex="mcp server ready",
                kill_timeout_sec=10,
            ),
        ),
        MCPIntegration(
            id="mcp.cics.catalog",
            name="CICS Catalog MCP",
            description="Discovers CICS transactions and program dispatch mappings.",
            tags=["cics", "online"],
            transport=StdioTransport(
                kind="stdio",
                command="cics-catalog-mcp",
                args=["--stdio"],
                cwd="/opt/renova/tools/cics-catalog",
                env={"LOG_LEVEL": "info"},
                env_aliases={"CICS_TOKEN": "alias.cics.token"},
                restart_on_exit=True,
                readiness_regex="mcp server ready",
                kill_timeout_sec=10,
            ),
        ),
        MCPIntegration(
            id="mcp.db2.catalog",
            name="DB2 Catalog MCP",
            description="Introspects DB2 schemas or DDL bundles for physical data model.",
            tags=["db2", "ddl", "schema"],
            transport=StdioTransport(
                kind="stdio",
                command="db2-catalog-mcp",
                args=["--stdio"],
                cwd="/opt/renova/tools/db2-catalog",
                env={"LOG_LEVEL": "info"},
                env_aliases={
                    "DB2_CONN": "alias.db2.conn",
                    "DB2_USERNAME": "alias.db2.user",
                    "DB2_PASSWORD": "alias.db2.pass",
                },
                restart_on_exit=True,
                readiness_regex="mcp server ready",
                kill_timeout_sec=10,
            ),
        ),
        MCPIntegration(
            id="mcp.dataset.scanner",
            name="Dataset Scanner MCP",
            description="Parses VSAM/SEQ metadata and schema hints from datasets.",
            tags=["vsam", "seq", "dataset"],
            transport=StdioTransport(
                kind="stdio",
                command="dataset-scanner-mcp",
                args=["--stdio"],
                cwd="/opt/renova/tools/dataset-scanner",
                env={"LOG_LEVEL": "info"},
                env_aliases={"MAINFRAME_TOKEN": "alias.mf.token"},
                restart_on_exit=True,
                readiness_regex="mcp server ready",
                kill_timeout_sec=10,
            ),
        ),
        MCPIntegration(
            id="mcp.graph.indexer",
            name="Graph Indexer MCP",
            description="Builds call graphs, job flows, and dataset dependency edges.",
            tags=["graph", "index", "inventory"],
            transport=StdioTransport(
                kind="stdio",
                command="graph-indexer-mcp",
                args=["--stdio"],
                cwd="/opt/renova/tools/graph-indexer",
                env={"LOG_LEVEL": "info"},
                env_aliases={},
                restart_on_exit=True,
                readiness_regex="mcp server ready",
                kill_timeout_sec=10,
            ),
        ),
        MCPIntegration(
            id="mcp.lineage.engine",
            name="Lineage Engine MCP",
            description="Computes conservative field-level lineage from IO ops and steps.",
            tags=["lineage", "data"],
            transport=StdioTransport(
                kind="stdio",
                command="lineage-engine-mcp",
                args=["--stdio"],
                cwd="/opt/renova/tools/lineage-engine",
                env={"LOG_LEVEL": "info"},
                env_aliases={},
                restart_on_exit=True,
                readiness_regex="mcp server ready",
                kill_timeout_sec=10,
            ),
        ),
        MCPIntegration(
            id="mcp.workflow.miner",
            name="Workflow Miner MCP",
            description="Derives batch workflows by stitching job and call graphs.",
            tags=["workflow", "batch"],
            transport=StdioTransport(
                kind="stdio",
                command="workflow-miner-mcp",
                args=["--stdio"],
                cwd="/opt/renova/tools/workflow-miner",
                env={"LOG_LEVEL": "info"},
                env_aliases={},
                restart_on_exit=True,
                readiness_regex="mcp server ready",
                kill_timeout_sec=10,
            ),
        ),
        MCPIntegration(
            id="mcp.diagram.exporter",
            name="Diagram Exporter MCP",
            description="Renders workflow processes into diagram JSON (and adapters).",
            tags=["diagram", "render"],
            transport=StdioTransport(
                kind="stdio",
                command="diagram-exporter-mcp",
                args=["--stdio"],
                cwd="/opt/renova/tools/diagram-exporter",
                env={"LOG_LEVEL": "info"},
                env_aliases={},
                restart_on_exit=True,
                readiness_regex="mcp server ready",
                kill_timeout_sec=10,
            ),
        ),
    ]

    # 3) Replace-by-ID create
    created = 0
    for integ in targets:
        try:
            if await svc.get(integ.id):
                try:
                    await svc.delete(integ.id, actor="seed")
                    log.info("[capability.seeds.integrations] replaced: %s (deleted old)", integ.id)
                except AttributeError:
                    log.warning("[capability.seeds.integrations] delete() not available; create() may fail on unique IDs")
        except Exception:
            pass

        await svc.create(integ, actor="seed")
        log.info("[capability.seeds.integrations] created: %s (%s)", integ.id, _transport_str(integ.transport))
        created += 1

    log.info("[capability.seeds.integrations] Done (created=%d)", created)
