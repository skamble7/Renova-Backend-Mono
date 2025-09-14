# services/artifact-service/app/seeds/seed_registry.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.dal.kind_registry_dal import upsert_kind

LATEST = "1.0.0"

# ─────────────────────────────────────────────────────────────
# Canonical seed docs (exactly as specified by the user)
# ─────────────────────────────────────────────────────────────
KIND_DOCS: List[Dict[str, Any]] = [
    {
        "_id": "cam.asset.repo_snapshot",
        "title": "Repository Snapshot",
        "summary": "Commit-level trace for the cloned source repo used in a learning run.",
        "category": "generic",
        "aliases": ["cam.asset.git_snapshot"],
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["repo", "commit", "branch", "paths_root"],
                "properties": {
                    "repo": {"type": "string", "description": "Remote URL or origin name"},
                    "commit": {"type": "string"},
                    "branch": {"type": "string"},
                    "paths_root": {"type": "string", "description": "Filesystem mount/volume path used by tools"},
                    "tags": {"type": "array", "items": {"type": "string"}}
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {
                "system": "Validate and normalize a Git snapshot into strict JSON. Do not invent fields.",
                "strict_json": True
            },
            "identity": {"natural_key": ["repo", "commit"]},
            "examples": [{
                "repo": "https://git.example.com/legacy/cards.git",
                "commit": "8f2c1b...",
                "branch": "main",
                "paths_root": "/mnt/src/cards"
            }]
        }]
    },
    {
        "_id": "cam.asset.source_index",
        "title": "Source Index",
        "summary": "Inventory of files in the cloned repo with type detection for COBOL/JCL/etc.",
        "category": "generic",
        "aliases": ["cam.asset.repo_index"],
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["root", "files"],
                "properties": {
                    "root": {"type": "string"},
                    "files": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["relpath", "size_bytes", "sha256", "kind"],
                            "properties": {
                                "relpath": {"type": "string"},
                                "size_bytes": {"type": "integer"},
                                "sha256": {"type": "string"},
                                "kind": {
                                    "type": "string",
                                    "enum": ["cobol", "copybook", "jcl", "ddl", "bms", "other"]
                                },
                                "language_hint": {"type": "string"},
                                "encoding": {"type": "string"},
                                "program_id_guess": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {
                "system": "Given a raw file walk, emit a strict typed inventory mapping each file to a kind used by downstream parsers. Do not include files outside the root.",
                "strict_json": True
            },
            "depends_on": {
                "hard": ["cam.asset.repo_snapshot"],
                "context_hint": "Use `paths_root` from the repo snapshot to anchor relpaths."
            },
            "identity": {"natural_key": ["root"]},
            "examples": [{
                "root": "/mnt/src/cards",
                "files": [
                    {"relpath": "batch/POSTTRAN.cbl", "size_bytes": 12453, "sha256": "...", "kind": "cobol"},
                    {"relpath": "batch/POSTTRAN.jcl", "size_bytes": 213, "sha256": "...", "kind": "jcl"},
                    {"relpath": "copy/CUSTREC.cpy", "size_bytes": 982, "sha256": "...", "kind": "copybook"}
                ]
            }]
        }]
    },
    {
        "_id": "cam.cobol.program",
        "title": "COBOL Program",
        "summary": "Parsed COBOL program structure (divisions, paragraphs, CALL/PERFORM, IO ops).",
        "category": "cobol",
        "aliases": [],
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["program_id", "source", "divisions", "paragraphs"],
                "properties": {
                    "program_id": {"type": "string"},
                    "source": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["relpath", "sha256"],
                        "properties": {"relpath": {"type": "string"}, "sha256": {"type": "string"}}
                    },
                    "divisions": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "identification": {"type": "object", "additionalProperties": True},
                            "environment": {"type": "object", "additionalProperties": True},
                            "data": {"type": "object", "additionalProperties": True},
                            "procedure": {"type": "object", "additionalProperties": True}
                        }
                    },
                    "paragraphs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "performs": {"type": "array", "items": {"type": "string"}},
                                "calls": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["target"],
                                        "properties": {
                                            "target": {"type": "string", "description": "PROGRAM-ID if resolvable, else literal"},
                                            "dynamic": {"type": "boolean", "default": False}
                                        }
                                    }
                                },
                                "io_ops": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["op", "dataset_ref"],
                                        "properties": {
                                            "op": {"type": "string", "enum": ["READ", "WRITE", "OPEN", "CLOSE", "REWRITE"]},
                                            "dataset_ref": {"type": "string"},
                                            "fields": {"type": "array", "items": {"type": "string"}}
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "copybooks_used": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "array", "items": {"type": "string"}}
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {
                "system": "Normalize ProLeap/cb2xml output into this canonical shape. Preserve names; do not invent CALL targets.",
                "strict_json": True
            },
            "depends_on": {
                "hard": ["cam.asset.source_index"],
                "soft": ["cam.cobol.copybook"],
                "context_hint": "Map `source.relpath` to a file in Source Index. Collect copybook names used."
            },
            "identity": {"natural_key": ["program_id"]},
            "examples": [{
                "program_id": "POSTTRAN",
                "source": {"relpath": "batch/POSTTRAN.cbl", "sha256": "..."},
                "divisions": {"identification": {}, "environment": {}, "data": {}, "procedure": {}},
                "paragraphs": [{"name": "MAIN", "performs": ["VALIDATE-INPUT"], "calls": [], "io_ops": []}]
            }]
        }]
    },
    {
        "_id": "cam.cobol.copybook",
        "title": "COBOL Copybook",
        "summary": "Structured data items parsed from COPY members.",
        "category": "cobol",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "source", "items"],
                "properties": {
                    "name": {"type": "string"},
                    "source": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["relpath", "sha256"],
                        "properties": {"relpath": {"type": "string"}, "sha256": {"type": "string"}}
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["level", "name", "picture"],
                            "properties": {
                                "level": {"type": "string"},
                                "name": {"type": "string"},
                                "picture": {"type": "string"},
                                "occurs": {"type": "integer"},
                                "children": {"type": "array", "items": {"$ref": "#"}}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {"system": "Normalize copybook AST into a strict tree. Do not lose levels or PIC clauses.", "strict_json": True},
            "depends_on": {"hard": ["cam.asset.source_index"]},
            "identity": {"natural_key": ["name"]},
            "examples": [{
                "name": "CUSTREC",
                "source": {"relpath": "copy/CUSTREC.cpy", "sha256": "..."},
                "items": [{"level": "01", "name": "CUST-REC", "picture": "", "children": [
                    {"level": "05", "name": "CUST-ID", "picture": "X(10)"}]}]
            }]
        }]
    },
    {
        "_id": "cam.jcl.job",
        "title": "JCL Job",
        "summary": "Job metadata and ordered step graph extracted from JCL.",
        "category": "cobol",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["job_name", "source", "steps"],
                "properties": {
                    "job_name": {"type": "string"},
                    "source": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["relpath", "sha256"],
                        "properties": {"relpath": {"type": "string"}, "sha256": {"type": "string"}}
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["step_name", "seq", "program", "dds"],
                            "properties": {
                                "step_name": {"type": "string"},
                                "seq": {"type": "integer"},
                                "program": {"type": "string"},
                                "condition": {"type": "string"},
                                "dds": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["ddname", "direction"],
                                        "properties": {
                                            "ddname": {"type": "string"},
                                            "dataset": {"type": "string"},
                                            "direction": {"type": "string", "enum": ["IN", "OUT", "INOUT"]}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {"system": "Parse JCL into an ordered list of steps with DD statements. Keep program names as written.", "strict_json": True},
            "depends_on": {"hard": ["cam.asset.source_index"]},
            "identity": {"natural_key": ["job_name"]},
            "examples": [{
                "job_name": "POSTTRAN",
                "source": {"relpath": "batch/POSTTRAN.jcl", "sha256": "..."},
                "steps": [{
                    "step_name": "STEP1", "seq": 1, "program": "POSTTRAN",
                    "dds": [
                        {"ddname": "INFILE", "dataset": "TRAN.IN", "direction": "IN"},
                        {"ddname": "OUTFILE", "dataset": "LEDGER.OUT", "direction": "OUT"}
                    ]
                }]
            }]
        }]
    },
    {
        "_id": "cam.jcl.step",
        "title": "JCL Step",
        "summary": "A single JCL step extracted for cross-referencing with programs and datasets.",
        "category": "cobol",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["job_name", "step_name", "seq", "program", "dds"],
                "properties": {
                    "job_name": {"type": "string"},
                    "step_name": {"type": "string"},
                    "seq": {"type": "integer"},
                    "program": {"type": "string"},
                    "dds": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["ddname", "direction"],
                            "properties": {
                                "ddname": {"type": "string"},
                                "dataset": {"type": "string"},
                                "direction": {"type": "string", "enum": ["IN", "OUT", "INOUT"]}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {"system": "Emit one strict record per JCL step to simplify graph indexing.", "strict_json": True},
            "depends_on": {"hard": ["cam.jcl.job"]},
            "identity": {"natural_key": ["job_name", "step_name"]},
            "examples": [{
                "job_name": "POSTTRAN",
                "step_name": "STEP1",
                "seq": 1,
                "program": "POSTTRAN",
                "dds": [{"ddname": "INFILE", "dataset": "TRAN.IN", "direction": "IN"}]
            }]
        }]
    },
    {
        "_id": "cam.cics.transaction",
        "title": "CICS Transaction Map",
        "summary": "Online transaction → program dispatch mapping.",
        "category": "cobol",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["region", "transactions"],
                "properties": {
                    "region": {"type": "string"},
                    "transactions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["tranid", "program"],
                            "properties": {
                                "tranid": {"type": "string"},
                                "program": {"type": "string"},
                                "mapset": {"type": "string"},
                                "commarea": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {"system": "Normalize CICS catalogs into a simple transaction map.", "strict_json": True},
            "depends_on": {"soft": ["cam.asset.source_index"]},
            "identity": {"natural_key": ["region"]},
            "examples": [{
                "region": "CICSPROD",
                "transactions": [{"tranid": "PAY1", "program": "PAYMENT"}, {"tranid": "BAL1", "program": "BALENQ"}]
            }]
        }]
    },
    {
        "_id": "cam.data.model",
        "title": "Data Model",
        "summary": "Logical and physical data structures (entities, tables, datasets).",
        "category": "data",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["logical", "physical"],
                "properties": {
                    "logical": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "fields"],
                            "properties": {
                                "name": {"type": "string"},
                                "fields": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["name", "type"],
                                        "properties": {
                                            "name": {"type": "string"},
                                            "type": {"type": "string"},
                                            "source_refs": {"type": "array", "items": {"type": "string"}}
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "physical": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name", "type"],
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string", "enum": ["DB2_TABLE", "VSAM", "SEQ", "FILE"]},
                                "columns": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "required": ["name", "pic_or_sqltype"],
                                        "properties": {"name": {"type": "string"}, "pic_or_sqltype": {"type": "string"}}
                                    }
                                },
                                "source_refs": {"type": "array", "items": {"type": "string"}}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {
                "system": "Map copybook fields and DB2/DDL into a normalized logical/physical model. Do not invent entities; aggregate identical record layouts.",
                "strict_json": True,
                "variants": [
                    {"name": "cobol-first", "when": {"stack": "cobol"}, "system": "Prefer copybooks as truth; fold DB2 later."}
                ]
            },
            "depends_on": {
                "hard": ["cam.cobol.copybook"],
                "soft": ["cam.jcl.job", "cam.jcl.step"],
                "context_hint": "Use copybook trees to propose logical entities; attach physical refs from JCL DD datasets or DB2 DDL if present."
            },
            "identity": {"natural_key": ["logical[*].name"]},
            "examples": [{
                "logical": [{"name": "Transaction", "fields": [{"name": "AMOUNT", "type": "NUMERIC(9,2)"}]}],
                "physical": [{
                    "name": "TRAN.IN", "type": "SEQ",
                    "columns": [{"name": "AMOUNT", "pic_or_sqltype": "S9(7)V99"}]
                }]
            }]
        }]
    },
    {
        "_id": "cam.data.dictionary",
        "title": "Domain Data Dictionary",
        "summary": "Business terms and definitions mined from copybooks/columns.",
        "category": "domain",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["terms"],
                "properties": {
                    "terms": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["term", "definition"],
                            "properties": {
                                "term": {"type": "string"},
                                "definition": {"type": "string"},
                                "aliases": {"type": "array", "items": {"type": "string"}},
                                "source_refs": {"type": "array", "items": {"type": "string"}}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {
                "system": "Extract a business-friendly data dictionary from copybook/table names with concise definitions. No prose outside JSON.",
                "strict_json": True
            },
            "depends_on": {"hard": ["cam.cobol.copybook"], "soft": ["cam.data.model"]},
            "identity": {"natural_key": ["terms[*].term"]},
            "examples": [{
                "terms": [{"term": "Account Balance", "definition": "Current monetary balance on an account.", "aliases": ["BAL", "ACCT-BAL"]}]
            }]
        }]
    },
    {
        "_id": "cam.data.lineage",
        "title": "Data Lineage",
        "summary": "Field-level read/write lineage across programs, steps, and datasets.",
        "category": "data",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["edges"],
                "properties": {
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["from", "to", "op"],
                            "properties": {
                                "from": {"type": "string", "description": "qualified source e.g., PROGRAM.PARAGRAPH.FIELD or DATASET.FIELD"},
                                "to": {"type": "string", "description": "qualified target"},
                                "op": {"type": "string", "enum": ["READ", "WRITE", "TRANSFORM"]},
                                "evidence": {"type": "array", "items": {"type": "string"}}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {"system": "Emit lineage edges only where there is evidence (IO ops, assignments). Be conservative.", "strict_json": True},
            "depends_on": {"hard": ["cam.cobol.program", "cam.jcl.step"], "soft": ["cam.data.model"]},
            "identity": {"natural_key": ["from", "to", "op"]},
            "examples": [{
                "edges": [
                    {"from": "TRAN.IN.AMOUNT", "to": "POSTTRAN.MAIN.AMOUNT", "op": "READ"},
                    {"from": "POSTTRAN.MAIN.BALANCE", "to": "LEDGER.OUT.BALANCE", "op": "WRITE"}
                ]
            }]
        }]
    },
    {
        "_id": "cam.asset.service_inventory",
        "title": "Service/Asset Inventory",
        "summary": "Catalog of programs, jobs, transactions, datasets discovered in the run.",
        "category": "generic",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["programs", "jobs", "datasets", "transactions"],
                "properties": {
                    "programs": {"type": "array", "items": {"type": "string"}},
                    "jobs": {"type": "array", "items": {"type": "string"}},
                    "datasets": {"type": "array", "items": {"type": "string"}},
                    "transactions": {"type": "array", "items": {"type": "string"}}
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {"system": "Aggregate identifiers from upstream facts into a single inventory. Do not rename.", "strict_json": True},
            "depends_on": {"hard": ["cam.cobol.program", "cam.jcl.job"], "soft": ["cam.cics.transaction"]},
            "identity": {"natural_key": ["programs", "jobs", "datasets", "transactions"]},
            "examples": [{
                "programs": ["POSTTRAN"],
                "jobs": ["POSTTRAN"],
                "datasets": ["TRAN.IN", "LEDGER.OUT"],
                "transactions": []
            }]
        }]
    },
    {
        "_id": "cam.asset.dependency_inventory",
        "title": "Dependency Inventory",
        "summary": "Call graph, job flow, and dataset dependencies as adjacency lists.",
        "category": "generic",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["call_graph", "job_flow", "dataset_deps"],
                "properties": {
                    "call_graph": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["from", "to"],
                            "properties": {"from": {"type": "string"}, "to": {"type": "string"}, "dynamic": {"type": "boolean"}}
                        }
                    },
                    "job_flow": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["job", "step", "seq", "program"],
                            "properties": {
                                "job": {"type": "string"},
                                "step": {"type": "string"},
                                "seq": {"type": "integer"},
                                "program": {"type": "string"}
                            }
                        }
                    },
                    "dataset_deps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["producer", "dataset", "consumer"],
                            "properties": {
                                "producer": {"type": "string"},
                                "dataset": {"type": "string"},
                                "consumer": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {"system": "Build deterministic edges from parsed facts. Do not infer missing endpoints.", "strict_json": True},
            "depends_on": {"hard": ["cam.cobol.program", "cam.jcl.step"]},
            "identity": {"natural_key": ["call_graph", "job_flow", "dataset_deps"]},
            "examples": [{
                "call_graph": [],
                "job_flow": [{"job": "POSTTRAN", "step": "STEP1", "seq": 1, "program": "POSTTRAN"}],
                "dataset_deps": [{"producer": "STEP1", "dataset": "LEDGER.OUT", "consumer": "DOWNSTREAM"}]
            }]
        }]
    },
    {
        "_id": "cam.workflow.process",
        "title": "Workflow Process",
        "summary": "BPMN/UML-Activity-like process describing batch or entity-centric flows.",
        "category": "workflow",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "type", "nodes", "edges"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {"type": "string", "enum": ["batch", "entity"]},
                    "lanes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["id", "label"],
                            "properties": {"id": {"type": "string"}, "label": {"type": "string"}}
                        }
                    },
                    "nodes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["id", "kind", "label"],
                            "properties": {
                                "id": {"type": "string"},
                                "kind": {"type": "string", "enum": ["start", "end", "task", "gateway", "event"]},
                                "label": {"type": "string"},
                                "lane": {"type": "string"},
                                "refs": {"type": "array", "items": {"type": "string"}}
                            }
                        }
                    },
                    "edges": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["from", "to"],
                            "properties": {
                                "from": {"type": "string"},
                                "to": {"type": "string"},
                                "condition": {"type": "string"}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {
                "system": "Given inventories and dependency graphs, emit a minimal process graph. Prefer deterministic stitching for batch; use naming heuristics only for labels.",
                "strict_json": True,
                "variants": [
                    {"name": "entity-centric", "when": {"mode": "entity"}, "system": "Slice graphs around fields/entities in cam.data.model and produce a business-readable flow."}
                ]
            },
            "depends_on": {"hard": ["cam.asset.dependency_inventory"], "soft": ["cam.data.model", "cam.data.lineage"]},
            "identity": {"natural_key": ["name", "type"]},
            "examples": [{
                "name": "POSTTRAN Batch",
                "type": "batch",
                "lanes": [{"id": "job", "label": "JCL Job"}],
                "nodes": [
                    {"id": "n0", "kind": "start", "label": "Start"},
                    {"id": "n1", "kind": "task", "label": "POSTTRAN"},
                    {"id": "n2", "kind": "end", "label": "End"}
                ],
                "edges": [{"from": "n0", "to": "n1"}, {"from": "n1", "to": "n2"}]
            }]
        }]
    },
    {
        "_id": "cam.diagram.activity",
        "title": "Activity Diagram",
        "summary": "Activity/flow rendering of a workflow process.",
        "category": "diagram",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_process", "diagram"],
                "properties": {
                    "source_process": {"type": "string"},
                    "diagram": {"type": "object", "additionalProperties": True}
                }
            },
            "additional_props_policy": "allow",
            "prompt": {"system": "Render the referenced workflow process as an activity diagram JSON. Preserve node and edge ids.", "strict_json": True},
            "depends_on": {"hard": ["cam.workflow.process"]},
            "identity": {"natural_key": ["source_process"]},
            "adapters": [{"type": "dsl", "dsl": {"to_plantuml": "activity_dsl_to_puml"}}],
            "examples": [{"source_process": "POSTTRAN Batch", "diagram": {"nodes": [], "edges": []}}]
        }]
    },
    {
        "_id": "cam.domain.dictionary",
        "title": "Domain Dictionary",
        "summary": "Normalized business vocabulary used across artifacts.",
        "category": "domain",
        "status": "active",
        "latest_schema_version": LATEST,
        "schema_versions": [{
            "version": LATEST,
            "json_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["entries"],
                "properties": {
                    "entries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["term", "kind"],
                            "properties": {
                                "term": {"type": "string"},
                                "kind": {"type": "string", "enum": ["entity", "event", "metric", "policy", "other"]},
                                "definition": {"type": "string"},
                                "aliases": {"type": "array", "items": {"type": "string"}},
                                "mappings": {"type": "array", "items": {"type": "string"}}
                            }
                        }
                    }
                }
            },
            "additional_props_policy": "forbid",
            "prompt": {"system": "Produce consistent, de-duplicated business terms grounded in upstream copybooks and data model. Keep definitions concise and non-ambiguous.", "strict_json": True},
            "depends_on": {"hard": ["cam.data.model", "cam.data.dictionary"]},
            "identity": {"natural_key": ["entries[*].term"]},
            "examples": [{
                "entries": [{
                    "term": "Transaction",
                    "kind": "entity",
                    "definition": "A financial posting.",
                    "aliases": ["TXN"],
                    "mappings": ["copybook:CUST-REC", "table:TRAN.IN"]
                }]
            }]
        }]
    },
]

# ─────────────────────────────────────────────────────────────
# Seeder
# ─────────────────────────────────────────────────────────────
def seed_registry() -> None:
    now = datetime.utcnow()
    for doc in KIND_DOCS:
        # Ensure common top-level fields exist
        doc.setdefault("aliases", [])
        doc.setdefault("policies", {})
        doc["created_at"] = doc.get("created_at", now)
        doc["updated_at"] = now
        upsert_kind(doc)

if __name__ == "__main__":
    seed_registry()
    print(f"Seeded {len(KIND_DOCS)} kinds into registry.")
