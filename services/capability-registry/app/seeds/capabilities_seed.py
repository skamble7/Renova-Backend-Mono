# services/capability-registry/app/seeds/capabilities_seed.py
from __future__ import annotations

import os
import logging
from typing import List, Dict, Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from ..dal.capability_dal import ensure_indexes
from ..models.capability_pack import GlobalCapabilityCreate
from ..services.artifact_registry_client import ArtifactRegistryClient

logger = logging.getLogger("capability.seeds")

SKIP_IF_EXISTS = os.getenv("CAPABILITIES_SEED_SKIP_IF_EXISTS", "1") not in ("0", "false", "False", "no", "NO")
VALIDATE_KINDS = os.getenv("CAPABILITIES_SEED_VALIDATE_KINDS", "0") in ("1", "true", "True", "yes", "YES")


def _collect_kinds(capabilities: List[Dict[str, Any]]) -> List[str]:
    kinds: List[str] = []
    for c in capabilities:
        kinds.extend(c.get("produces_kinds") or [])
        kinds.extend(c.get("requires_kinds") or [])
    seen = set()
    out: List[str] = []
    for k in kinds:
        if k and k not in seen:
            seen.add(k)
            out.append(k)
    return out


# ─────────────────────────────────────────────────────────────
# Capability Seed
# ─────────────────────────────────────────────────────────────
CAPABILITY_SEED: List[Dict[str, Any]] = [
    # =========================================================
    # Source Code Fetching (new for GitHub fetcher)
    # =========================================================
    {
        "id": "cap.source.fetch_from_github",
        "name": "Fetch Source from GitHub",
        "description": "Clone a GitHub repository at a given ref and expose repository, manifest, and file artifacts.",
        "tags": ["fetcher", "scm", "github"],
        "parameters_schema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string"},
                "ref": {"type": "string"}
            },
            "required": ["repo"]
        },
        "produces_kinds": [
            "cam.source.repository",
            "cam.source.manifest",
            "cam.source.file"
        ],
        "requires_kinds": [],
        "agent": None,
    },

    # =========================================================
    # Domain & Semantics
    # =========================================================
    {
        "id": "cap.domain.mine_legacy_terms",
        "name": "Mine Legacy Terms from Code",
        "description": "Extract a glossary of domain terms from COBOL programs, copybooks, comments, and JCL.",
        "tags": ["domain", "semantics", "nlp", "cobol", "jcl"],
        "parameters_schema": None,
        "produces_kinds": ["cam.domain.legacy_terms"],
        "requires_kinds": ["cam.cobol.program", "cam.cobol.copybook", "cam.jcl.job"],
        "agent": None,
    },
    {
        "id": "cap.domain.expand_acronyms",
        "name": "Expand System Acronyms",
        "description": "Identify and expand system-specific acronyms by cross-referencing code symbols and comments.",
        "tags": ["domain", "semantics", "nlp"],
        "parameters_schema": None,
        "produces_kinds": ["cam.domain.acronyms"],
        "requires_kinds": ["cam.cobol.program", "cam.jcl.job"],
        "agent": None,
    },
    {
        "id": "cap.domain.infer_business_rules",
        "name": "Infer Business Rules from Conditions",
        "description": "Recover business rules from COBOL IF/EVALUATE logic, PERFORM conditions, and validation patterns.",
        "tags": ["domain", "rules", "analysis", "cobol"],
        "parameters_schema": None,
        "produces_kinds": ["cam.domain.business_rules"],
        "requires_kinds": ["cam.cobol.program", "cam.cobol.paragraph_flow"],
        "agent": None,
    },

    # =========================================================
    # Legacy Components
    # =========================================================
    {
        "id": "cap.code.index_legacy_components",
        "name": "Index Legacy Components",
        "description": "Build an inventory of programs, modules, copybooks, procs, and utilities.",
        "tags": ["code", "inventory", "cobol", "jcl"],
        "parameters_schema": None,
        "produces_kinds": ["cam.code.legacy_component"],
        "requires_kinds": [],
        "agent": None,
    },
    {
        "id": "cap.code.build_call_hierarchy",
        "name": "Build Call Hierarchy",
        "description": "Generate static/dynamic call graph across programs, copybooks, and invoked utilities.",
        "tags": ["code", "graph", "calls"],
        "parameters_schema": None,
        "produces_kinds": ["cam.code.call_hierarchy"],
        "requires_kinds": ["cam.cobol.program"],
        "agent": None,
    },
    {
        "id": "cap.code.map_dependencies",
        "name": "Map Code Dependencies",
        "description": "Derive dependencies between code units and external systems (DB2, VSAM, files, queues).",
        "tags": ["code", "dependencies"],
        "parameters_schema": None,
        "produces_kinds": ["cam.code.dependency_map"],
        "requires_kinds": ["cam.cobol.program", "cam.jcl.step", "cam.db2.table_usage", "cam.vsam.cluster"],
        "agent": None,
    },
    {
        "id": "cap.code.infer_interfaces",
        "name": "Infer Program Interfaces",
        "description": "Summarize inputs/outputs for programs/modules (parameters, files, tables, return codes).",
        "tags": ["code", "interfaces"],
        "parameters_schema": None,
        "produces_kinds": ["cam.code.interface"],
        "requires_kinds": ["cam.cobol.program", "cam.cobol.copybook", "cam.db2.table_usage", "cam.vsam.cluster"],
        "agent": None,
    },

    # =========================================================
    # Data & Storage
    # =========================================================
    {
        "id": "cap.data.derive_legacy_structures",
        "name": "Derive Legacy Data Structures",
        "description": "Normalize copybook/record layouts into canonical legacy data structures.",
        "tags": ["data", "copybook", "structure"],
        "parameters_schema": None,
        "produces_kinds": ["cam.data.legacy_structure"],
        "requires_kinds": ["cam.cobol.copybook"],
        "agent": None,
    },
    {
        "id": "cap.data.map_legacy_to_modern_model",
        "name": "Map Legacy Data to Modern Model",
        "description": "Map legacy record layouts to target domain entities and modern data model.",
        "tags": ["data", "mapping"],
        "parameters_schema": None,
        "produces_kinds": ["cam.data.mapping"],
        "requires_kinds": ["cam.data.legacy_structure", "cam.domain.legacy_terms"],
        "agent": None,
    },
    {
        "id": "cap.data.build_usage_matrix",
        "name": "Build Data Usage Matrix",
        "description": "Compute where and how data elements are read/updated across programs and jobs.",
        "tags": ["data", "usage"],
        "parameters_schema": None,
        "produces_kinds": ["cam.data.usage_matrix"],
        "requires_kinds": ["cam.cobol.program", "cam.db2.table_usage", "cam.jcl.step"],
        "agent": None,
    },

    # =========================================================
    # Workflows & Jobs
    # =========================================================
    {
        "id": "cap.workflow.extract_legacy_jobs",
        "name": "Extract Legacy Jobs",
        "description": "Extract batch jobs from JCL to a canonical job representation for modernization.",
        "tags": ["workflow", "jcl", "batch"],
        "parameters_schema": None,
        "produces_kinds": ["cam.workflow.legacy_job"],
        "requires_kinds": ["cam.jcl.job"],
        "agent": None,
    },
    {
        "id": "cap.workflow.build_job_flow",
        "name": "Build Job Flow Graph",
        "description": "Construct directed graph of job execution order and inter-job dependencies.",
        "tags": ["workflow", "graph"],
        "parameters_schema": None,
        "produces_kinds": ["cam.workflow.job_flow"],
        "requires_kinds": ["cam.workflow.legacy_job", "cam.jcl.step"],
        "agent": None,
    },
    {
        "id": "cap.workflow.infer_scheduling",
        "name": "Infer Scheduling Rules",
        "description": "Recover triggers, calendars, and dependency rules from JCL, PROCs, and scheduler metadata.",
        "tags": ["workflow", "scheduling"],
        "parameters_schema": None,
        "produces_kinds": ["cam.workflow.scheduling"],
        "requires_kinds": ["cam.workflow.legacy_job"],
        "agent": None,
    },

    # =========================================================
    # Architecture Mapping
    # =========================================================
    {
        "id": "cap.mapping.programs_to_services",
        "name": "Map Programs to Candidate Services/APIs",
        "description": "Propose service/API boundaries from programs and their interfaces/flows.",
        "tags": ["mapping", "modernization"],
        "parameters_schema": None,
        "produces_kinds": ["cam.mapping.legacy_to_modern"],
        "requires_kinds": ["cam.cobol.program", "cam.code.interface", "cam.code.call_hierarchy"],
        "agent": None,
    },
    {
        "id": "cap.mapping.data_to_entities",
        "name": "Map Data to Domain Entities",
        "description": "Map record layouts and fields to target domain entities.",
        "tags": ["mapping", "data"],
        "parameters_schema": None,
        "produces_kinds": ["cam.mapping.data_to_entity"],
        "requires_kinds": ["cam.data.legacy_structure", "cam.domain.legacy_terms"],
        "agent": None,
    },
    {
        "id": "cap.mapping.jobs_to_processes",
        "name": "Map Jobs to Modern Processes",
        "description": "Map JCL jobs to modern orchestration definitions (e.g., Airflow, Spring Batch).",
        "tags": ["mapping", "workflow"],
        "parameters_schema": None,
        "produces_kinds": ["cam.mapping.job_to_process"],
        "requires_kinds": ["cam.workflow.legacy_job", "cam.workflow.job_flow", "cam.domain.business_rules"],
        "agent": None,
    },

    # =========================================================
    # Operational & Non-functional
    # =========================================================
    {
        "id": "cap.ops.profile_performance",
        "name": "Profile Performance",
        "description": "Aggregate runtime stats and build performance profiles for programs and jobs.",
        "tags": ["ops", "performance"],
        "parameters_schema": None,
        "produces_kinds": ["cam.ops.performance_profile"],
        "requires_kinds": [],
        "agent": None,
    },
    {
        "id": "cap.ops.catalog_errors",
        "name": "Catalog Errors and Return Codes",
        "description": "Extract and classify error codes/messages used across programs and jobs.",
        "tags": ["ops", "errors"],
        "parameters_schema": None,
        "produces_kinds": ["cam.ops.error_catalog"],
        "requires_kinds": ["cam.cobol.program", "cam.jcl.job"],
        "agent": None,
    },
    {
        "id": "cap.ops.infer_security_rules",
        "name": "Infer Security Rules",
        "description": "Recover access-control, dataset permissions, and auth checks from code and JCL.",
        "tags": ["ops", "security"],
        "parameters_schema": None,
        "produces_kinds": ["cam.ops.security_rules"],
        "requires_kinds": ["cam.cobol.program", "cam.jcl.job"],
        "agent": None,
    },

    # =========================================================
    # COBOL / JCL / DB2 / VSAM Specific
    # =========================================================
    {
        "id": "cap.cobol.parse_copybooks",
        "name": "Parse COBOL Copybooks",
        "description": "Extract raw copybook definitions via deterministic parsers.",
        "tags": ["cobol", "copybook", "parser"],
        "parameters_schema": None,
        "produces_kinds": ["cam.cobol.copybook"],
        "requires_kinds": [],
        "agent": None,
    },
    {
        "id": "cap.cobol.parse_programs",
        "name": "Parse COBOL Programs",
        "description": "Extract program metadata (divisions, I/O, entry points) using COBOL parsers.",
        "tags": ["cobol", "program", "parser"],
        "parameters_schema": None,
        "produces_kinds": ["cam.cobol.program"],
        "requires_kinds": [],
        "agent": None,
    },
    {
        "id": "cap.cobol.derive_paragraph_flow",
        "name": "Derive COBOL Paragraph Flow",
        "description": "Build control flow at paragraph/section level from parsed programs.",
        "tags": ["cobol", "control-flow"],
        "parameters_schema": None,
        "produces_kinds": ["cam.cobol.paragraph_flow"],
        "requires_kinds": ["cam.cobol.program"],
        "agent": None,
    },
    {
        "id": "cap.cobol.derive_file_mapping",
        "name": "Derive COBOL File Mapping",
        "description": "Map file I/O statements to VSAM clusters and flat files.",
        "tags": ["cobol", "files", "vsam"],
        "parameters_schema": None,
        "produces_kinds": ["cam.cobol.file_mapping"],
        "requires_kinds": ["cam.cobol.program"],
        "agent": None,
    },
    {
        "id": "cap.jcl.parse_jobs",
        "name": "Parse JCL Jobs",
        "description": "Extract JCL jobs (JOB, PROC, INCLUDE) and normalize metadata.",
        "tags": ["jcl", "batch", "parser"],
        "parameters_schema": None,
        "produces_kinds": ["cam.jcl.job"],
        "requires_kinds": [],
        "agent": None,
    },
    {
        "id": "cap.jcl.derive_steps",
        "name": "Derive JCL Steps",
        "description": "Extract steps, DD statements, executed programs, and datasets.",
        "tags": ["jcl", "batch"],
        "parameters_schema": None,
        "produces_kinds": ["cam.jcl.step"],
        "requires_kinds": ["cam.jcl.job"],
        "agent": None,
    },
    {
        "id": "cap.db2.scan_table_usage",
        "name": "Scan DB2 Table Usage",
        "description": "Identify DB2 tables/views accessed by COBOL programs and SQL.",
        "tags": ["db2", "sql"],
        "parameters_schema": None,
        "produces_kinds": ["cam.db2.table_usage"],
        "requires_kinds": ["cam.cobol.program"],
        "agent": None,
    },
    {
        "id": "cap.vsam.discover_clusters",
        "name": "Discover VSAM Clusters",
        "description": "Catalog VSAM clusters referenced in COBOL/JCL and their record layouts linkage.",
        "tags": ["vsam", "files"],
        "parameters_schema": None,
        "produces_kinds": ["cam.vsam.cluster"],
        "requires_kinds": ["cam.jcl.step"],
        "agent": None,
    },
]


async def _maybe_validate_kinds(capabilities: List[Dict[str, Any]]):
    if not VALIDATE_KINDS:
        return
    client = ArtifactRegistryClient()
    kinds = _collect_kinds(capabilities)
    if not kinds:
        return
    try:
        valid, invalid = await client.validate_kinds(kinds)
    except Exception as e:
        logger.warning("Capability seed: skipping kind validation (artifact-service not reachable)", exc_info=e)
        return
    if invalid:
        logger.warning(
            "Capability seed: some kinds are not registered in artifact-service",
            extra={"invalid": invalid, "valid": valid},
        )


async def run_capabilities_seed(db: AsyncIOMotorDatabase):
    await ensure_indexes(db)

    existing_count = await db["capabilities"].count_documents({})
    if SKIP_IF_EXISTS and existing_count > 0:
        logger.info("Capabilities seed: skipped (collection already has records)", extra={"count": existing_count})
        return {"skipped": True, "existing": existing_count}

    await _maybe_validate_kinds(CAPABILITY_SEED)

    inserted = 0
    replaced = 0
    for raw in CAPABILITY_SEED:
        doc = GlobalCapabilityCreate(**raw).model_dump()
        res = await db["capabilities"].find_one_and_replace(
            {"id": doc["id"]}, doc, upsert=True, return_document=True
        )
        if res is None:
            inserted += 1
        else:
            replaced += 1

    total = await db["capabilities"].count_documents({})
    logger.info("Capabilities seed done", extra={"inserted": inserted, "replaced": replaced, "total": total})
    return {"skipped": False, "inserted": inserted, "replaced": replaced, "total": total}
