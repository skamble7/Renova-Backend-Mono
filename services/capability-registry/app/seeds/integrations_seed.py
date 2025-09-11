# services/capability-registry/app/seeds/integrations_seed.py
from __future__ import annotations

import os, logging
from typing import Dict, Any, List
from motor.motor_asyncio import AsyncIOMotorDatabase

from ..dal.integrations_dal import (
    ensure_indexes as ensure_integ_indexes,
    get_connector, create_connector,
    get_tool, create_tool,
)
from ..models.integrations import ConnectorCreate, ToolCreate
from ..services.artifact_registry_client import ArtifactRegistryClient

logger = logging.getLogger("capability.seeds.integrations")

SKIP_IF_EXISTS = os.getenv("INTEGRATIONS_SEED_SKIP_IF_EXISTS", "1") in ("1", "true", "True", "yes", "YES")
VALIDATE_KINDS = os.getenv("INTEGRATIONS_SEED_VALIDATE_KINDS", "1") in ("1", "true", "True", "yes", "YES")


def _collect_tool_kinds(tools: List[Dict[str, Any]]) -> List[str]:
    kinds: List[str] = []
    for t in tools:
        kinds.extend(t.get("produces_kinds") or [])
        kinds.extend(t.get("requires_kinds") or [])
    seen = set()
    out: List[str] = []
    for k in kinds:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


# -------------------------------------------------------------------
# Connectors
# -------------------------------------------------------------------
SEED_CONNECTORS: List[Dict[str, Any]] = [
    # New: GitHub SCM fetcher
    {
        "key": "fetcher.scm.github",
        "type": "repo",
        "vendor": "github",
        "version": "v1",
        "capabilities": ["scm-fetch", "scm-clone"],
        "config_schema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "format": "uri"},
                "token": {"type": "string"}
            },
            "required": ["base_url"],
            "additionalProperties": True
        },
        "secrets": ["token"],
        "doc_url": "https://docs.github.com/rest",
    },
    # COBOL parser connector
    {
        "key": "parser.cobol.proleap",
        "type": "parser",
        "vendor": "proleap+cb2xml",
        "version": "v1",
        "capabilities": ["cobol-parse", "copybook-xml", "paragraph-flow", "file-mapping"],
        "config_schema": {
            "type": "object",
            "properties": {"base_url": {"type": "string", "format": "uri"}},
            "required": ["base_url"],
            "additionalProperties": True,
        },
        "secrets": [],
        "doc_url": None,
    },
    # JCL parser connector (placeholder)
    {
        "key": "parser.jcl.example",
        "type": "parser",
        "vendor": "example",
        "version": "v1",
        "capabilities": ["jcl-parse"],
        "config_schema": {
            "type": "object",
            "properties": {"endpoint": {"type": "string"}},
            "required": ["endpoint"],
            "additionalProperties": True,
        },
        "secrets": ["api_key"],
        "doc_url": None,
    },
    # DB2 analyzer connector (placeholder)
    {
        "key": "analyzer.db2.example",
        "type": "custom",
        "vendor": "example",
        "version": "v1",
        "capabilities": ["db2-usage"],
        "config_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        "secrets": [],
        "doc_url": None,
    },
    # Agent connector for kind generation (diagram + other JSON kinds)
    # NOTE: models.integrations.ConnectorCreate.type does NOT include "agent" in its Literal,
    # so we register this as a generic custom connector.
    {
        "key": "agent.renova.kindgen",
        "type": "custom",  # was "agent" -> use "custom" to satisfy the enum
        "vendor": "renova",
        "version": "v1",
        "capabilities": ["kind-generate"],
        "config_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "max_tokens": {"type": "integer"}
            },
            "additionalProperties": True
        },
        "secrets": [],
        "doc_url": None
    },
]


# -------------------------------------------------------------------
# Tools
# -------------------------------------------------------------------
SEED_TOOLS: List[Dict[str, Any]] = [
    # GitHub fetch tool
    {
        "key": "tool.github.fetch",
        "connector_key": "fetcher.scm.github",
        "operation": "fetch",
        "input_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "ref": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["repo"],
            "additionalProperties": True
        },
        "output_schema": None,
        "produces_kinds": [
            "cam.source.repository",
            "cam.source.manifest",
            "cam.source.file"
        ],
        "requires_kinds": []
    },
    # COBOL parser tools
    {
        "key": "tool.cobol.parse",
        "connector_key": "parser.cobol.proleap",
        "operation": "parse",
        "input_schema": {
            "type": "object",
            "properties": {
                "dialect": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "string"}},
                "program_paths": {"type": "array", "items": {"type": "string"}},
            },
            "additionalProperties": True,
        },
        "output_schema": None,
        "produces_kinds": ["cam.cobol.program"],
        "requires_kinds": []
    },
    {
        "key": "tool.copybook.to_xml",
        "connector_key": "parser.cobol.proleap",
        "operation": "copybook_to_xml",
        "input_schema": {
            "type": "object",
            "properties": {
                "copybooks": {"type": "array", "items": {"type": "string"}},
                "encoding": {"type": "string"}
            },
            "additionalProperties": True,
        },
        "output_schema": None,
        "produces_kinds": ["cam.cobol.copybook"],
        "requires_kinds": []
    },
    {
        "key": "tool.cobol.flow",
        "connector_key": "parser.cobol.proleap",
        "operation": "paragraph_flow",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        "output_schema": None,
        "produces_kinds": ["cam.cobol.paragraph_flow"],
        "requires_kinds": ["cam.cobol.program"]
    },
    {
        "key": "tool.cobol.filemap",
        "connector_key": "parser.cobol.proleap",
        "operation": "file_mapping",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        "output_schema": None,
        "produces_kinds": ["cam.cobol.file_mapping"],
        "requires_kinds": ["cam.cobol.program"]
    },
    # JCL + DB2
    {
        "key": "tool.jcl.parse",
        "connector_key": "parser.jcl.example",
        "operation": "parse",
        "input_schema": {
            "type": "object",
            "properties": {"jcl_paths": {"type": "array", "items": {"type": "string"}}},
            "additionalProperties": True
        },
        "output_schema": None,
        "produces_kinds": ["cam.jcl.job", "cam.jcl.step"],
        "requires_kinds": []
    },
    {
        "key": "tool.db2.usage",
        "connector_key": "analyzer.db2.example",
        "operation": "scan_table_usage",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        "output_schema": None,
        "produces_kinds": ["cam.db2.table_usage"],
        "requires_kinds": ["cam.cobol.program"]
    },

    # Agent-backed diagram generators (one tool per kind)
    {
        "key": "tool.kindgen.diagram.job_flow",
        "connector_key": "agent.renova.kindgen",
        "operation": "generate",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_kind": {"const": "cam.diagram.job_flow"},
                "notation": {"type": "string", "enum": ["c4", "mermaid", "plantuml", "dot", "drawio"]},
                "context": {"type": "object"}
            },
            "required": ["target_kind"],
            "additionalProperties": True
        },
        "output_schema": None,
        "produces_kinds": ["cam.diagram.job_flow"],
        "requires_kinds": ["cam.workflow.job_flow"]
    },
    {
        "key": "tool.kindgen.diagram.call_graph",
        "connector_key": "agent.renova.kindgen",
        "operation": "generate",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_kind": {"const": "cam.diagram.call_graph"},
                "notation": {"type": "string", "enum": ["c4", "mermaid", "plantuml", "dot", "drawio"]},
                "context": {"type": "object"}
            },
            "required": ["target_kind"],
            "additionalProperties": True
        },
        "output_schema": None,
        "produces_kinds": ["cam.diagram.call_graph"],
        "requires_kinds": ["cam.code.call_hierarchy"]
    },
    {
        "key": "tool.kindgen.diagram.data_flow",
        "connector_key": "agent.renova.kindgen",
        "operation": "generate",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_kind": {"const": "cam.diagram.data_flow"},
                "notation": {"type": "string", "enum": ["c4", "mermaid", "plantuml", "dot", "drawio"]},
                "context": {"type": "object"}
            },
            "required": ["target_kind"],
            "additionalProperties": True
        },
        "output_schema": None,
        "produces_kinds": ["cam.diagram.data_flow"],
        "requires_kinds": [
            "cam.workflow.job_flow",
            "cam.code.call_hierarchy",
            "cam.cobol.file_mapping",
            "cam.db2.table_usage",
            "cam.vsam.cluster"
        ]
    },
    {
        "key": "tool.kindgen.diagram.system_context",
        "connector_key": "agent.renova.kindgen",
        "operation": "generate",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_kind": {"const": "cam.diagram.system_context"},
                "notation": {"type": "string", "enum": ["c4", "mermaid", "plantuml", "dot", "drawio"]},
                "context": {"type": "object"}
            },
            "required": ["target_kind"],
            "additionalProperties": True
        },
        "output_schema": None,
        "produces_kinds": ["cam.diagram.system_context"],
        "requires_kinds": []
    },
]


async def _maybe_validate_kinds():
    if not VALIDATE_KINDS:
        return
    kinds = _collect_tool_kinds(SEED_TOOLS)
    if not kinds:
        return
    client = ArtifactRegistryClient()
    try:
        valid, invalid = await client.validate_kinds(kinds)
    except Exception as e:
        logger.warning("Integrations seed: skipping kind validation (artifact-service not reachable)", exc_info=e)
        return
    if invalid:
        logger.warning(
            "Integrations seed: some kinds are not registered in artifact-service",
            extra={"invalid": list(invalid), "valid": valid},
        )


async def run_integrations_seed(db: AsyncIOMotorDatabase):
    await ensure_integ_indexes(db)

    logger.info("Integrations seed: env",
                extra={
                    "INTEGRATIONS_SEED_SKIP_IF_EXISTS": os.getenv("INTEGRATIONS_SEED_SKIP_IF_EXISTS"),
                    "INTEGRATIONS_SEED_VALIDATE_KINDS": os.getenv("INTEGRATIONS_SEED_VALIDATE_KINDS"),
                })

    await _maybe_validate_kinds()

    c_added = 0
    for raw in SEED_CONNECTORS:
        existing = await get_connector(db, raw["key"])
        if not existing:
            await create_connector(db, ConnectorCreate(**raw))
            c_added += 1

    t_added = 0
    for raw in SEED_TOOLS:
        existing = await get_tool(db, raw["key"])
        if not existing:
            if not await get_connector(db, raw["connector_key"]):
                seed = next((c for c in SEED_CONNECTORS if c["key"] == raw["connector_key"]), None)
                if seed:
                    await create_connector(db, ConnectorCreate(**seed))
                    c_added += 1
                else:
                    logger.error("Tool references unknown connector",
                                 extra={"tool_key": raw["key"], "connector_key": raw["connector_key"]})
                    continue
            await create_tool(db, ToolCreate(**raw))
            t_added += 1

    total_c = await db["integrations_connectors"].count_documents({})
    total_t = await db["integrations_tools"].count_documents({})
    logger.info("Integrations seed done", extra={
        "connectors_added": c_added,
        "tools_added": t_added,
        "total_connectors": total_c,
        "total_tools": total_t
    })
    return {"skipped": False, "connectors_added": c_added, "tools_added": t_added,
            "total_connectors": total_c, "total_tools": total_t}
