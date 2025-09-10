# services/artifact-service/app/seeds/seed_registry.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.dal.kind_registry_dal import upsert_kind

LATEST = "1.0.0"

# ─────────────────────────────────────────────────────────────
# Canonical list of kinds Renova can produce (expanded)
# ─────────────────────────────────────────────────────────────
ALL_KINDS: List[str] = [
    # ── Diagrams (Draw.io)
    "cam.diagram.context",
    "cam.diagram.class",
    "cam.diagram.sequence",
    "cam.diagram.component",
    "cam.diagram.deployment",
    "cam.diagram.activity",
    "cam.diagram.state",

    # ── Domain & Semantics
    "cam.domain.dictionary",
    "cam.domain.capability_model",
    "cam.domain.legacy_terms",
    "cam.domain.acronyms",
    "cam.domain.business_rules",

    # ── Source / SCM (filesystem hand-off)
    "cam.source.checkout_ref",
    "cam.source.manifest",

    # ── Code / modernized source (generic)
    "cam.code.module",
    "cam.code.service",
    "cam.code.api",
    "cam.code.table",

    # ── Code analysis (legacy)
    "cam.code.call_hierarchy",
    "cam.code.dependency_map",
    "cam.code.interface",

    # ── Data
    "cam.data.model",
    "cam.data.dictionary",
    "cam.data.lineage",
    "cam.data.legacy_structure",
    "cam.data.mapping",
    "cam.data.usage_matrix",

    # ── Workflow
    "cam.workflow.process",
    "cam.workflow.batch_job",
    "cam.workflow.job_flow",
    "cam.workflow.scheduling",

    # ── Mapping (legacy → modern)
    "cam.mapping.entity",
    "cam.mapping.service",
    "cam.mapping.dataflow",
    "cam.mapping.legacy_to_modern",
    "cam.mapping.data_to_entity",
    "cam.mapping.job_to_process",

    # ── COBOL
    "cam.cobol.program",
    "cam.cobol.copybook",
    "cam.cobol.transaction",
    "cam.cobol.file",
    "cam.cobol.map",
    "cam.cobol.paragraph_flow",
    "cam.cobol.file_mapping",

    # ── JCL
    "cam.jcl.job",
    "cam.jcl.proc",
    "cam.jcl.step",
    "cam.jcl.dd_statement",

    # ── DB2 / VSAM
    "cam.db2.table_usage",
    "cam.vsam.cluster",

    # ── Ops
    "cam.ops.runbook",
    "cam.ops.playbook",

    # ── Asset Inventories
    "cam.asset.service_inventory",
    "cam.asset.api_inventory",
]

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def category_of(kind: str) -> str:
    return kind.split(".")[1] if kind.count(".") >= 2 else "misc"

def artifact_of(kind: str) -> str:
    return kind.split(".")[-1]

DRAWIO_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "language": {"const": "drawio"},
        "instructions": {"type": "string", "pattern": r"^<mxfile[\s\S]*</mxfile>$"},
        "summary": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"rel": {"type": "string"}, "href": {"type": "string"}, "title": {"type": "string"}}
            }
        }
    },
    "required": ["language", "instructions"]
}

def _string_id():
    return {"type": "string", "minLength": 1}

def _name_desc():
    return {"name": {"type": "string", "minLength": 1}, "description": {"type": "string"}}

# ─────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────
def schema_for(kind: str) -> Dict[str, Any]:
    cat = category_of(kind)
    art = artifact_of(kind)

    # ── Diagrams
    if cat == "diagram":
        return DRAWIO_SCHEMA

    # ── Domain & Semantics
    if kind == "cam.domain.dictionary":
        return {
            "type": "object", "additionalProperties": False,
            "properties": {
                "terms": {
                    "type": "array",
                    "items": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "term": {"type": "string"},
                            "definitions": {"type": "array", "items": {"type": "string"}},
                            "synonyms": {"type": "array", "items": {"type": "string"}},
                            "acronyms": {"type": "array", "items": {"type": "string"}},
                            "examples": {"type": "array", "items": {"type": "string"}},
                            "sources": {"type": "array", "items": {"type": "string"}},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                        },
                        "required": ["term"]
                    }
                }
            },
            "required": ["terms"]
        }
    if kind == "cam.domain.capability_model":
        return {
            "type": "object", "additionalProperties": False,
            "properties": {
                "capabilities": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": False, "properties": {
                        "id": _string_id(), **_name_desc(), "level": {"type": "integer","minimum":1,"maximum":5},
                        "parent_id": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}
                    }, "required": ["id","name"]}
                },
                "relationships": {
                    "type": "array",
                    "items": {"type": "object", "additionalProperties": False, "properties": {
                        "from": _string_id(), "to": _string_id(), "type": {"type": "string"}
                    }}
                }
            },
            "required": ["capabilities"]
        }
    if kind == "cam.domain.legacy_terms":
        return {
            "type": "object","additionalProperties": False,
            "properties": {
                "items": {"type": "array","items": {"type":"object","additionalProperties": False,"properties":{
                    "term":{"type":"string"},
                    "where_found":{"type":"array","items":{"type":"string"}},
                    "normalized":{"type":"string"},
                    "notes":{"type":"string"},
                    "confidence":{"type":"number","minimum":0,"maximum":1}
                },"required":["term"]}}
            },
            "required": ["items"]
        }
    if kind == "cam.domain.acronyms":
        return {
            "type": "object","additionalProperties": False,
            "properties": {
                "acronyms":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "acronym":{"type":"string"},
                    "expansion":{"type":"string"},
                    "notes":{"type":"string"},
                    "where_found":{"type":"array","items":{"type":"string"}}
                },"required":["acronym","expansion"]}}
            },
            "required": ["acronyms"]
        }
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

    # ── Source / SCM (filesystem hand-off)
    if kind == "cam.source.checkout_ref":
        return {
            "type": "object", "additionalProperties": False,
            "properties": {
                "workspace": {"type": "string"},
                "root": {"type": "string"},              # absolute path inside landing zone
                "repo": {"type": "string"},
                "ref": {"type": "string"},
                "commit": {"type": "string"},
                "paths": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["workspace", "root", "repo", "commit", "paths"]
        }
    if kind == "cam.source.manifest":
        return {
            "type": "object", "additionalProperties": False,
            "properties": {
                "repo": {"type": "string"},
                "ref": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["repo", "files"]
        }

    # ── Code / Generic
    if kind == "cam.code.module":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "key":{"type":"string"}, **_name_desc(),
                "language":{"type":"string"},
                "path":{"type":"string"},
                "responsibilities":{"type":"array","items":{"type":"string"}},
                "dependencies":{"type":"array","items":{"type":"string"}},
                "metrics":{"type":"object","additionalProperties":False,"properties":{
                    "loc":{"type":"integer","minimum":0},
                    "cyclomatic_complexity":{"type":"number","minimum":0}
                }}
            },
            "required":["key","name"]
        }
    if kind == "cam.code.service":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"key":{"type":"string"}, **_name_desc(),
                "layer":{"type":"string"},
                "depends_on":{"type":"array","items":{"type":"string"}},
                "apis":{"type":"array","items":{"type":"string"}}
            },
            "required":["key","name"]
        }
    if kind == "cam.code.api":
        return {
            "type":"object","additionalProperties":False,
            "properties":{**_name_desc(),
                "version":{"type":"string"},
                "endpoints":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "method":{"type":"string"},
                    "path":{"type":"string"},
                    "summary":{"type":"string"},
                    "request":{"type":"object"},
                    "responses":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                        "status":{"type":"integer"},
                        "body":{"type":"object"},
                        "description":{"type":"string"}
                    },"required":["status"]}},
                    "errors":{"type":"array","items":{"type":"string"}}
                },"required":["method","path"]}}
            },
            "required":["name","endpoints"]
        }

    # ── Code analysis (legacy)
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
    if kind == "cam.code.dependency_map":
        return {
            "type": "object", "additionalProperties": False,
            "properties": {
                "dependencies": {"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "from":{"type":"string"}, "to":{"type":"string"}, "kind":{"type":"string"}  # file/db2/vsam/queue
                },"required":["from","to"]}}
            },
            "required": ["dependencies"]
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

    # ── Data
    if kind == "cam.data.model":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "entities":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "name":{"type":"string"},
                    "attributes":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                        "name":{"type":"string"},"type":{"type":"string"},
                        "nullable":{"type":"boolean"},"notes":{"type":"string"}
                    },"required":["name","type"]}},
                    "primary_key":{"type":"array","items":{"type":"string"}}
                },"required":["name","attributes"]}},
                "relationships":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "from":{"type":"string"},"to":{"type":"string"},"cardinality":{"type":"string"}
                },"required":["from","to"]}}
            },
            "required":["entities"]
        }
    if kind == "cam.data.dictionary":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"elements":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "name":{"type":"string"},"type":{"type":"string"},"length":{"type":"integer"},
                "scale":{"type":"integer"},"description":{"type":"string"},
                "sources":{"type":"array","items":{"type":"string"}}
            },"required":["name","type"]}}},
            "required":["elements"]
        }
    if kind == "cam.data.lineage":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "nodes":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "id": _string_id(), "label":{"type":"string"}, "type":{"type":"string"}
                },"required":["id","label"]}},
                "edges":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "from": _string_id(), "to": _string_id(), "op":{"type":"string"}
                },"required":["from","to"]}}
            },
            "required":["nodes","edges"]
        }
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
    if kind == "cam.data.mapping":
        # generic mapping (source -> target) for data elements
        return {
            "type":"object","additionalProperties":False,
            "properties":{"mappings":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "source":{"type":"string"},
                "target":{"type":"string"},
                "transform":{"type":"string"},
                "confidence":{"type":"number","minimum":0,"maximum":1},
                "notes":{"type":"string"}
            },"required":["source","target"]}}},
            "required":["mappings"]
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

    # ── Workflow
    if kind == "cam.workflow.process":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                **_name_desc(),
                "swimlanes":{"type":"array","items":{"type":"string"}},
                "steps":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "id": _string_id(),"name":{"type":"string"},"lane":{"type":"string"},"kind":{"type":"string"},"notes":{"type":"string"}
                },"required":["id","name"]}},
                "transitions":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "from": _string_id(),"to": _string_id(),"condition":{"type":"string"}
                },"required":["from","to"]}}
            },
            "required":["name","steps","transitions"]
        }
    if kind == "cam.workflow.batch_job":
        return {
            "type":"object","additionalProperties":False,
            "properties":{
                "job_id":{"type":"string"}, **_name_desc(),
                "schedule":{"type":"string"},
                "steps":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                    "seq":{"type":"integer","minimum":1},
                    "program":{"type":"string"},
                    "params":{"type":"array","items":{"type":"string"}},
                    "datasets":{"type":"array","items":{"type":"string"}},
                    "condition":{"type":"string"}
                },"required":["seq","program"]}}
            },
            "required":["job_id","name","steps"]
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

    # ── Mapping
    if kind in ("cam.mapping.entity", "cam.mapping.data_to_entity"):
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
    if kind in ("cam.mapping.service", "cam.mapping.legacy_to_modern"):
        return {
            "type":"object","additionalProperties":False,
            "properties":{"links":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "legacy":{"type":"string"},
                "modern":{"type":"string"},
                "rationale":{"type":"string"},
                "confidence":{"type":"number","minimum":0,"maximum":1}
            },"required":["legacy","modern"]}}}
        }
    if kind in ("cam.mapping.dataflow", "cam.mapping.job_to_process"):
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
    if kind == "cam.cobol.transaction":
        return {"type":"object","additionalProperties":False,"properties":{
            "tran_id":{"type":"string"},
            "programs":{"type":"array","items":{"type":"string"}},
            "inputs":{"type":"array","items":{"type":"string"}},
            "outputs":{"type":"array","items":{"type":"string"}}
        },"required":["tran_id","programs"]}
    if kind == "cam.cobol.file":
        return {"type":"object","additionalProperties":False,"properties":{
            "ddname":{"type":"string"},
            "dataset":{"type":"string"},
            "organization":{"type":"string"},
            "record_layout":{"type":"string"},
            "access":{"type":"string"}
        },"required":["ddname","dataset"]}
    if kind == "cam.cobol.map":
        return {"type":"object","additionalProperties":False,"properties":{
            "mapset":{"type":"string"},
            "map":{"type":"string"},
            "fields":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "name":{"type":"string"},
                "type":{"type":"string"},
                "length":{"type":"integer"},
                "position":{"type":"object","properties":{"row":{"type":"integer"},"col":{"type":"integer"}},"additionalProperties":False}
            },"required":["name"]}}
        },"required":["mapset","map"]}
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

    # ── JCL
    if kind == "cam.jcl.job":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"jobname":{"type":"string"},"account":{"type":"string"},
                "class":{"type":"string"},"message_class":{"type":"string"},
                "steps":{"type":"array","items":{"type":"string"}}},
            "required":["jobname"]
        }
    if kind == "cam.jcl.proc":
        return {"type":"object","additionalProperties":False,"properties":{
            "procname":{"type":"string"},
            "params":{"type":"object"},
            "steps":{"type":"array","items":{"type":"string"}}
        },"required":["procname"]}
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
    if kind == "cam.jcl.dd_statement":
        return {
            "type":"object","additionalProperties":False,
            "properties":{"ddname":{"type":"string"},"dataset":{"type":"string"},
                "disp":{"type":"string"},"space":{"type":"string"},"dcb":{"type":"string"}},
            "required":["ddname"]
        }

    # ── DB2 / VSAM
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

    # ── Ops
    if kind == "cam.ops.runbook":
        return {"type":"object","additionalProperties":False,"properties":{
            **_name_desc(),
            "scenarios":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "id": _string_id(), "title":{"type":"string"}, "steps":{"type":"array","items":{"type":"string"}}
            },"required":["id","title","steps"]}}
        },"required":["name","scenarios"]}
    if kind == "cam.ops.playbook":
        return {"type":"object","additionalProperties":False,"properties":{
            **_name_desc(),
            "triggers":{"type":"array","items":{"type":"string"}},
            "actions":{"type":"array","items":{"type":"string"}},
            "owners":{"type":"array","items":{"type":"string"}}
        },"required":["name"]}

    # ── Assets
    if kind == "cam.asset.service_inventory":
        return {"type":"object","additionalProperties":False,"properties":{
            "services":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "key":{"type":"string"},
                "name":{"type":"string"},
                "owner":{"type":"string"},
                "tier":{"type":"string"},
                "status":{"type":"string"}
            },"required":["key","name"]}}
        },"required":["services"]}
    if kind == "cam.asset.api_inventory":
        return {"type":"object","additionalProperties":False,"properties":{
            "apis":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "name":{"type":"string"},
                "version":{"type":"string"},
                "service":{"type":"string"},
                "endpoints":{"type":"integer","minimum":0}
            },"required":["name"]}}
        },"required":["apis"]}

    # Fallback (should not be used)
    return {"type": "object", "additionalProperties": False}

# ─────────────────────────────────────────────────────────────
# Identity rules
# ─────────────────────────────────────────────────────────────
def identity_for(kind: str) -> Dict[str, Any]:
    # Diagrams
    if kind.startswith("cam.diagram."):
        return {"natural_key": ["name"]}

    # Domain
    if kind.startswith("cam.domain."):
        return {"natural_key": ["name"]}

    # Source / SCM
    if kind == "cam.source.checkout_ref":
        # one per workspace+repo+commit
        return {"natural_key": ["workspace", "repo", "commit"]}
    if kind == "cam.source.manifest":
        return {"natural_key": ["repo", "ref"]}

    # Code & analysis
    if kind in ("cam.code.module","cam.code.service","cam.code.api","cam.code.table",
                "cam.code.call_hierarchy","cam.code.dependency_map","cam.code.interface"):
        return {"natural_key": ["name"]}

    # Data
    if kind.startswith("cam.data."):
        return {"natural_key": ["name"]}

    # Workflow
    if kind.startswith("cam.workflow."):
        return {"natural_key": ["name"]}

    # Mapping
    if kind.startswith("cam.mapping."):
        return {"natural_key": ["name"]}

    # COBOL / JCL specifics
    if kind.startswith("cam.cobol.") or kind.startswith("cam.jcl."):
        return {"natural_key": ["name"]}

    # DB2 / VSAM
    if kind in ("cam.db2.table_usage", "cam.vsam.cluster"):
        return {"natural_key": ["name"]}

    # Assets
    if kind.startswith("cam.asset."):
        return {"natural_key": ["name"]}

    return {"natural_key": ["name"]}

# ─────────────────────────────────────────────────────────────
# Prompt config (LLM generation disabled by default here)
# ─────────────────────────────────────────────────────────────
def prompt_for(kind: str) -> Dict[str, Any]:
    return {
        "system": "You are RENOVA. Output strictly valid JSON conforming to the provided JSON Schema. Do not include prose.",
        "user_template": None,
        "variants": [],
        "io_hints": {"strict": True},
        "strict_json": True,
        "prompt_rev": 1,
    }

def build_kind_doc(kind: str) -> Dict[str, Any]:
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
