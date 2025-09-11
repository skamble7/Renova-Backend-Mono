# services/artifact-service/app/seeds/seed_registry.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.dal.kind_registry_dal import upsert_kind

LATEST = "1.0.0"

# ─────────────────────────────────────────────────────────────
# Canonical list of kinds for COBOL modernization (Core + Nice + Diagrams)
# ─────────────────────────────────────────────────────────────
ALL_KINDS: List[str] = [
    # ── Source / SCM
    "cam.source.repository",
    "cam.source.manifest",
    "cam.source.file",

    # ── COBOL code understanding
    "cam.cobol.program",
    "cam.cobol.copybook",
    "cam.cobol.paragraph_flow",
    "cam.cobol.file_mapping",

    # ── Generic code analysis (language-agnostic)
    "cam.code.call_hierarchy",
    "cam.code.interface",

    # ── Data access
    "cam.db2.table_usage",
    "cam.vsam.cluster",

    # ── JCL / workflow
    "cam.jcl.job",
    "cam.jcl.step",
    "cam.workflow.job_flow",
    "cam.workflow.scheduling",

    # ── Domain / rules
    "cam.domain.business_rules",

    # ── Nice-to-have data structure & usage
    "cam.data.legacy_structure",
    "cam.data.usage_matrix",

    # ── Mapping (legacy → modern)
    "cam.mapping.program_to_service",
    "cam.mapping.job_to_process",
    "cam.mapping.data_to_entity",
    "cam.mapping.legacy_to_modern",

    # ── Diagrams (renderer-agnostic, with optional rendered text)
    "cam.diagram.system_context",
    "cam.diagram.container_view",
    "cam.diagram.component_view",
    "cam.diagram.deployment_view",
    "cam.diagram.job_flow",
    "cam.diagram.call_graph",
    "cam.diagram.data_flow",
    "cam.diagram.er",
]

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def category_of(kind: str) -> str:
    return kind.split(".")[1] if kind.count(".") >= 2 else "misc"

def artifact_of(kind: str) -> str:
    return kind.split(".")[-1]

def _string_id():
    return {"type": "string", "minLength": 1}

def _name_desc():
    return {"name": {"type": "string", "minLength": 1}, "description": {"type": "string"}}

# ─────────────────────────────────────────────────────────────
# Diagram schema (notation + nodes/edges; optional rendered form)
# ─────────────────────────────────────────────────────────────
DIAGRAM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "notation": {"type": "string", "enum": ["c4", "mermaid", "plantuml", "dot", "drawio"]},
        "name": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": _string_id(),
                    "label": {"type": "string"},
                    "type": {"type": "string"},
                    "props": {"type": "object"},
                },
                "required": ["id", "label"],
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "from": _string_id(),
                    "to": _string_id(),
                    "label": {"type": "string"},
                    "props": {"type": "object"},
                },
                "required": ["from", "to"],
            },
        },
        "legend": {"type": "string"},
        "layout_hint": {"type": "string"},
        "rendered": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "language": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["language", "content"],
        },
    },
    "required": ["notation", "nodes", "edges"],
}

# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────
def schema_for(kind: str) -> Dict[str, Any]:
    # Diagrams (all share the same base schema)
    if kind.startswith("cam.diagram."):
        return DIAGRAM_SCHEMA

    # ── Source / SCM
    if kind == "cam.source.repository":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo": {"type": "string"},                  # e.g., https://github.com/org/repo
                "path": {"type": "string"},                  # local path in landing zone
                "commit": {"type": "string"},                # commit/sha or resolved ref
                "ref": {"type": "string"},                   # requested ref/branch/tag
            },
            "required": ["repo", "path", "commit"],
        }
    if kind == "cam.source.manifest":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo": {"type": "string"},
                "ref": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["repo", "files"],
        }
    if kind == "cam.source.file":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "repo": {"type": "string"},
                "ref": {"type": "string"},
                "path": {"type": "string"},                  # path relative to repo root
                "sha": {"type": "string"},
                "size": {"type": "integer", "minimum": 0},
            },
            "required": ["repo", "path"],
        }

    # ── COBOL
    if kind == "cam.cobol.program":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "program_id":{"type":"string"},
                "division":{"type":"object","additionalProperties":False,"properties":{
                    "identification":{"type":"object"},
                    "environment":{"type":"object"},
                    "data":{"type":"object"},
                    "procedure":{"type":"object"}
                }},
                "io":{"type":"object","additionalProperties":False,"properties":{
                    "files":{"type":"array","items":{"type":"string"}},
                    "db2_tables":{"type":"array","items":{"type":"string"}},
                    "queues":{"type":"array","items":{"type":"string"}}
                }},
                "calls":{"type":"array","items":{"type":"string"}},
                "paragraphs":{"type":"array","items":{"type":"string"}},
                "metrics":{"type":"object","properties":{"loc":{"type":"integer"}},"additionalProperties":False}
            },
            "required":["program_id"]
        }
    if kind == "cam.cobol.copybook":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "name":{"type":"string"},
                "raw":{"type":"string"},
                "fields":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "level":{"type":"integer"},
                    "name":{"type":"string"},
                    "pic":{"type":"string"},
                    "occurs":{"type":"integer"},
                    "redefines":{"type":"string"}
                },"required":["level","name"]}}
            },
            "required":["name","raw"]
        }
    if kind == "cam.cobol.paragraph_flow":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "program":{"type":"string"},
                "nodes":{"type":"array","items":{"type":"string"}},
                "edges":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "from":{"type":"string"}, "to":{"type":"string"}, "label":{"type":"string"}
                },"required":["from","to"]}}
            },
            "required":["program","nodes","edges"]
        }
    if kind == "cam.cobol.file_mapping":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "program":{"type":"string"},
                "files":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "ddname":{"type":"string"},
                    "dataset":{"type":"string"},
                    "vsam_cluster":{"type":"string"},
                    "access":{"type":"string"}
                },"required":["ddname"]}}
            },
            "required":["program","files"]
        }

    # ── Generic code analysis
    if kind == "cam.code.call_hierarchy":
        return {
            "type": "object", "additionalProperties": False,
            "properties": {
                "nodes": {"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "id": _string_id(), "program":{"type":"string"}
                },"required":["id","program"]}},
                "edges": {"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "from": _string_id(), "to": _string_id(), "type":{"type":"string","default":"call"}
                },"required":["from","to"]}}
            },
            "required": ["nodes","edges"]
        }
    if kind == "cam.code.interface":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "program":{"type":"string"},
                "inputs":{"type":"array","items":{"type":"string"}},    # params/files/tables
                "outputs":{"type":"array","items":{"type":"string"}},
                "return_codes":{"type":"array","items":{"type":"string"}}
            },
            "required":["program"]
        }

    # ── Data access
    if kind == "cam.db2.table_usage":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"tables":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "name":{"type":"string"},
                "ops":{"type":"array","items":{"type":"string"}}  # SELECT/INSERT/UPDATE/DELETE
            },"required":["name"]}}},
            "required":["tables"]
        }
    if kind == "cam.vsam.cluster":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"name":{"type":"string"},
                "dataset":{"type":"string"},
                "record_format":{"type":"string"},
                "key":{"type":"object","properties":{"field":{"type":"string"},"length":{"type":"integer"}},"additionalProperties":False}},
            "required":["name"]
        }

    # ── JCL / workflow
    if kind == "cam.jcl.job":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"jobname":{"type":"string"},"account":{"type":"string"},
                "class":{"type":"string"},"message_class":{"type":"string"},
                "steps":{"type":"array","items":{"type":"string"}}},
            "required":["jobname"]
        }
    if kind == "cam.jcl.step":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "stepname":{"type":"string"},
                "program":{"type":"string"},
                "proc_ref":{"type":"string"},
                "params":{"type":"array","items":{"type":"string"}},
                "dd":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "ddname":{"type":"string"},
                    "dataset":{"type":"string"},
                    "disp":{"type":"string"},
                    "dcb":{"type":"string"}
                },"required":["ddname"]}}
            },
            "required":["stepname"]
        }
    if kind == "cam.workflow.job_flow":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "nodes":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "id": _string_id(), "label":{"type":"string"}, "type":{"type":"string"}  # job/step
                },"required":["id","label"]}},
                "edges":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "from": _string_id(), "to": _string_id(), "label":{"type":"string"}
                },"required":["from","to"]}}
            },
            "required":["nodes","edges"]
        }
    if kind == "cam.workflow.scheduling":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "triggers":{"type":"array","items":{"type":"string"}},    # cron or descriptors
                "calendars":{"type":"array","items":{"type":"string"}},
                "predecessors":{"type":"array","items":{"type":"string"}},# job names/ids
                "windows":{"type":"array","items":{"type":"string"}}      # maintenance/business windows
            }
        }

    # ── Domain / rules
    if kind == "cam.domain.business_rules":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"rules":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "id": _string_id(),
                "name":{"type":"string"},
                "statement":{"type":"string"},
                "logic":{"type":"string"},
                "source_references":{"type":"array","items":{"type":"string"}},
                "impacts":{"type":"array","items":{"type":"string"}},
                "confidence":{"type":"number","minimum":0,"maximum":1}
            },"required":["id","name","statement"]}}},
            "required":["rules"]
        }

    # ── Data structure & usage
    if kind == "cam.data.legacy_structure":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "name":{"type":"string"},
                "records":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "name":{"type":"string"},
                    "fields":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                        "level":{"type":"integer"},"name":{"type":"string"},
                        "pic":{"type":"string"},"occurs":{"type":"integer"},
                        "redefines":{"type":"string"}
                    },"required":["name"]}}
                },"required":["name"]}}
            },
            "required":["name","records"]
        }
    if kind == "cam.data.usage_matrix":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"rows":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "program":{"type":"string"},
                "element":{"type":"string"},
                "operation":{"type":"string"}  # read/update/delete
            },"required":["program","element","operation"]}}},
            "required":["rows"]
        }

    # ── Mapping (legacy → modern)
    if kind == "cam.mapping.program_to_service":
        return {
            "type": "object", "additionalProperties": False,
            "properties": {
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "program": {"type": "string"},
                            "service": {"type": "string"},
                            "rationale": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": ["program", "service"],
                    },
                }
            },
            "required": ["links"],
        }
    if kind == "cam.mapping.job_to_process":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "nodes":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "id": _string_id(),"label":{"type":"string"},"type":{"type":"string"}
                },"required":["id","label"]}},
                "edges":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "from": _string_id(),"to": _string_id(),"label":{"type":"string"}
                },"required":["from","to"]}}
            },
            "required":["nodes","edges"]
        }
    if kind == "cam.mapping.data_to_entity":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"mappings":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "source":{"type":"string"},
                "target":{"type":"string"},
                "transform":{"type":"string"},
                "notes":{"type":"string"},
                "confidence":{"type":"number","minimum":0,"maximum":1}
            },"required":["source","target"]}}},
            "required":["mappings"]
        }
    if kind == "cam.mapping.legacy_to_modern":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"links":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "legacy":{"type":"string"},
                "modern":{"type":"string"},
                "rationale":{"type":"string"},
                "confidence":{"type":"number","minimum":0,"maximum":1}
            },"required":["legacy","modern"]}}}
        }

    # Fallback
    return {"type": "object", "additionalProperties": False}

# ─────────────────────────────────────────────────────────────
# Identity rules
# ─────────────────────────────────────────────────────────────
def identity_for(kind: str) -> Dict[str, Any]:
    # Diagrams
    if kind.startswith("cam.diagram."):
        return {"natural_key": ["name"]}

    # Source / SCM
    if kind == "cam.source.repository":
        return {"natural_key": ["repo", "commit"]}            # one per repo@commit
    if kind == "cam.source.manifest":
        return {"natural_key": ["repo", "ref"]}
    if kind == "cam.source.file":
        return {"natural_key": ["repo", "ref", "path"]}

    # Code & analysis
    if kind in ("cam.cobol.program", "cam.cobol.copybook", "cam.cobol.paragraph_flow",
                "cam.cobol.file_mapping", "cam.code.call_hierarchy", "cam.code.interface"):
        return {"natural_key": ["name"]}

    # Data access
    if kind in ("cam.db2.table_usage", "cam.vsam.cluster"):
        return {"natural_key": ["name"]}

    # JCL / workflow
    if kind in ("cam.jcl.job", "cam.jcl.step", "cam.workflow.job_flow", "cam.workflow.scheduling"):
        return {"natural_key": ["name"]}

    # Domain / rules
    if kind.startswith("cam.domain."):
        return {"natural_key": ["name"]}

    # Data structure & usage
    if kind.startswith("cam.data."):
        return {"natural_key": ["name"]}

    # Mapping
    if kind.startswith("cam.mapping."):
        return {"natural_key": ["name"]}

    return {"natural_key": ["name"]}

# ─────────────────────────────────────────────────────────────
# Dependencies (first-class): per-kind → DependsOnSpec (soft/hard/context_hint)
# These values are written into schema_versions[].depends_on and also referenced in prompts.
# ─────────────────────────────────────────────────────────────
def depends_on_for(kind: str) -> Optional[Dict[str, Any]]:
    # Diagrams with structured upstream kinds
    if kind == "cam.diagram.job_flow":
        return {"hard": ["cam.workflow.job_flow"], "soft": [], "context_hint": "Render jobs/steps and precedence as-is."}
    if kind == "cam.diagram.call_graph":
        return {"hard": ["cam.code.call_hierarchy"], "soft": [], "context_hint": "Use nodes/edges from the call hierarchy."}
    if kind == "cam.diagram.data_flow":
        return {
            "soft": [
                "cam.workflow.job_flow",
                "cam.code.call_hierarchy",
                "cam.cobol.file_mapping",
                "cam.db2.table_usage",
                "cam.vsam.cluster",
            ],
            "context_hint": "Prefer existing job/call/file/DB2/VSAM artifacts to drive data flow edges.",
        }
    if kind == "cam.diagram.er":
        return {"soft": ["cam.data.legacy_structure", "cam.mapping.data_to_entity"], "context_hint": "ER entities should align to legacy structures or mapped entities."}
    if kind in ("cam.diagram.system_context", "cam.diagram.container_view", "cam.diagram.component_view", "cam.diagram.deployment_view"):
        return {"soft": ["cam.mapping.legacy_to_modern", "cam.mapping.program_to_service"], "context_hint": "Place legacy and candidate modern services appropriately."}

    # Mappings
    if kind == "cam.mapping.program_to_service":
        return {"soft": ["cam.code.interface", "cam.code.call_hierarchy"], "context_hint": "Program boundaries should reflect interfaces and call graph cohesion."}
    if kind == "cam.mapping.job_to_process":
        return {"soft": ["cam.workflow.job_flow", "cam.jcl.job", "cam.jcl.step"], "context_hint": "Preserve control flow and step sequencing from JCL/job-flow."}
    if kind == "cam.mapping.data_to_entity":
        return {"soft": ["cam.data.legacy_structure"], "context_hint": "Map fields from legacy record layouts to target entities."}
    if kind == "cam.mapping.legacy_to_modern":
        return {"soft": ["cam.mapping.program_to_service", "cam.mapping.data_to_entity"], "context_hint": "Aggregate lower-level mappings into system-level viewpoints."}

    # Domain and usage often leverage upstream structured facts but are optional
    if kind == "cam.domain.business_rules":
        return {"soft": ["cam.cobol.paragraph_flow", "cam.cobol.program"], "context_hint": "Extract rules from IF/EVALUATE logic and validations."}
    if kind == "cam.data.usage_matrix":
        return {"soft": ["cam.cobol.program", "cam.db2.table_usage", "cam.jcl.step"], "context_hint": "Cross programs with elements and operations from parsers/analyzers."}

    # Source and raw analyzers don't require dependencies
    return None

# ─────────────────────────────────────────────────────────────
# Prompt config
# ─────────────────────────────────────────────────────────────
def prompt_for(kind: str) -> Dict[str, Any]:
    """
    Prompts enforce:
      1) Strict JSON only, conforming to the kind's JSON Schema.
      2) If the caller passes `context.related` with artifacts for any kinds declared in `depends_on`,
         you MUST reuse and stay consistent with them; otherwise, infer independently.
      3) Never invent fields outside the schema. Satisfy ALL required fields.
      4) Prefer empty arrays/objects over nulls where allowed.
    The executor/agent should pass:
      { "schema": <json_schema>, "context": { "related": { <kind>: [<artifacts>], ... } } }
    """
    deps = depends_on_for(kind)
    if deps:
        kinds = []
        kinds += list(deps.get("hard", []))
        kinds += list(deps.get("soft", []))
        kinds_clause = ", ".join(sorted(set(kinds)))
        guidance = deps.get("context_hint") or ""
        deps_txt = (
            f" Dependencies declared for this kind: [{kinds_clause}]. "
            f"When `context.related` includes any of these kinds, reuse identifiers, labels, "
            f"and relationships from those artifacts. {guidance}".strip()
        )
    else:
        deps_txt = " No explicit dependencies for this kind."

    system = (
        "You are RENOVA. Output strictly valid JSON that conforms EXACTLY to the provided JSON Schema. "
        "Do NOT include prose or any keys not defined by the schema. "
        "Populate every required field. "
        "Prefer concise values and use empty arrays/objects instead of nulls where appropriate."
        + deps_txt
    )

    return {
        "system": system,
        "user_template": None,
        "variants": [],
        "io_hints": {"strict": True},
        "strict_json": True,
        "prompt_rev": 3,
    }

# ─────────────────────────────────────────────────────────────
# Builder & seeder
# ─────────────────────────────────────────────────────────────
def build_kind_doc(kind: str) -> Dict[str, Any]:
    dep = depends_on_for(kind)
    return {
        "_id": kind,
        "title": artifact_of(kind).replace("_", " ").title(),
        "summary": f"Canonical artifact for {kind}",
        "category": category_of(kind),
        "aliases": [],
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [
            {
                "version": LATEST,
                "json_schema": schema_for(kind),
                "additional_props_policy": "forbid",
                "prompt": prompt_for(kind),
                "identity": identity_for(kind),
                "adapters": [],
                "migrators": [],
                "examples": [],
                # NEW: explicit dependency spec written with the schema version
                "depends_on": dep if dep else None,
            }
        ],
        "policies": {},
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

def seed_registry() -> None:
    for k in ALL_KINDS:
        upsert_kind(build_kind_doc(k))

if __name__ == "__main__":
    seed_registry()
    print(f"Seeded {len(ALL_KINDS)} kinds into registry.")
