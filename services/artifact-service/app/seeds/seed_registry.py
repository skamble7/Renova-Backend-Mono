# services/artifact-service/app/seeds/seed_registry.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from app.dal.kind_registry_dal import upsert_kind

LATEST = "1.0.0"

# ─────────────────────────────────────────────────────────────
# Canonical seed docs (with diagram_recipes)
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
            }],
            "diagram_recipes": [
                {
                    "id": "repo.mindmap",
                    "title": "Repo Snapshot Mindmap",
                    "view": "mindmap",
                    "language": "mermaid",
                    "description": "Quick overview of repo → branch/commit and tags.",
                    "template": """mindmap
  root(({{ data.repo }}))
    Branch: {{ data.branch }}
    Commit: {{ data.commit }}
    Paths Root: {{ data.paths_root }}
    Tags
      {% for t in (data.tags or []) %}{{ t }}
      {% endfor %}"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "source_index.treemap",
                    "title": "Source Index Treemap",
                    "view": "flowchart",
                    "language": "mermaid",
                    "description": "Kind-bucketed file overview.",
                    "prompt": {
                        "system": "Summarize the Source Index into a Mermaid flowchart grouping files by kind. Keep labels short; do not list more than 50 nodes.",
                        "strict_text": True
                    },
                    "renderer_hints": {"direction": "LR"}
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "program.mindmap",
                    "title": "Program → Divisions → Paragraphs (Mindmap)",
                    "view": "mindmap",
                    "language": "mermaid",
                    "description": "High-level overview: program root, divisions, and paragraph nodes.",
                    "template": """mindmap
  root(({{ data.program_id }}))
  {% if data.divisions.identification %}Identification{% endif %}
  {% if data.divisions.environment %}Environment{% endif %}
  {% if data.divisions.data %}Data{% endif %}
  Procedure
    {% for p in data.paragraphs %}{{ p.name }}
    {% endfor %}
classDef divisions fill:#eee,stroke:#999;"""
                },
                {
                    "id": "program.sequence",
                    "title": "Paragraph CALL / PERFORM Sequence",
                    "view": "sequence",
                    "language": "mermaid",
                    "description": "Dynamic interaction across paragraphs and called programs.",
                    "prompt": {
                        "system": "Given the canonical cam.cobol.program JSON, emit Mermaid sequence diagram instructions describing PERFORM and CALL interactions. Use paragraph names and PROGRAM-ID targets. Do not fabricate nodes.",
                        "strict_text": True
                    },
                    "renderer_hints": {"wrap": True}
                },
                {
                    "id": "program.flowchart",
                    "title": "Paragraph PERFORM Flow",
                    "view": "flowchart",
                    "language": "mermaid",
                    "description": "Control flow between paragraphs via PERFORM edges.",
                    "template": """flowchart TD
  START([{{ data.program_id }} START])
  {% for p in data.paragraphs %}
  {{ p.name | replace("-", "_") }}([{{ p.name }}])
  {% endfor %}
  {% if data.paragraphs|length > 0 %}START --> {{ data.paragraphs[0].name | replace("-", "_") }}{% endif %}
  {% for p in data.paragraphs %}
    {% for t in (p.performs or []) %}
  {{ p.name | replace("-", "_") }} --> {{ t | replace("-", "_") }}
    {% endfor %}
  {% endfor %}
  END([END])"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "copybook.mindmap",
                    "title": "Copybook Fields Mindmap",
                    "view": "mindmap",
                    "language": "mermaid",
                    "description": "Hierarchy of fields by levels.",
                    "template": """mindmap
  root(({{ data.name }}))
  {% for item in data.items %}
  {{ item.level }} {{ item.name }}
    {% for c in (item.children or []) %}{{ c.level }} {{ c.name }}
    {% endfor %}
  {% endfor %}"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "jcl.flow",
                    "title": "JCL Job Flow (Steps)",
                    "view": "flowchart",
                    "language": "mermaid",
                    "description": "Simple TD flow through steps by seq, annotated with program names.",
                    "template": """flowchart TD
  START([{{ data.job_name }} START])
  {% for s in data.steps|sort(attribute='seq') %}
  {{ s.step_name }}([{{ s.step_name }}\\n{{ s.program }}])
  {% endfor %}
  {% for s in data.steps|sort(attribute='seq') %}
    {% set next = loop.index0 + 1 %}
    {% if next < (data.steps|length) %}
  {{ data.steps[loop.index0].step_name }} --> {{ data.steps[next].step_name }}
    {% endif %}
  {% endfor %}
  END([END])"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "jcl.step.io",
                    "title": "JCL Step IO",
                    "view": "flowchart",
                    "language": "mermaid",
                    "description": "Visualize datasets in/out of a step.",
                    "template": """flowchart LR
  {{ data.step_name }}([{{ data.step_name }}\\n{{ data.program }}])
  {% for d in data.dds %}
    {% if d.direction == "IN" or d.direction == "INOUT" %}
  {{ d.ddname | replace("-", "_") }}([{{ d.dataset or d.ddname }}]) --> {{ data.step_name }}
    {% endif %}
    {% if d.direction == "OUT" or d.direction == "INOUT" %}
  {{ data.step_name }} --> {{ d.ddname | replace("-", "_") }}([{{ d.dataset or d.ddname }}])
    {% endif %}
  {% endfor %}"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "cics.map",
                    "title": "CICS Transaction → Program",
                    "view": "flowchart",
                    "language": "mermaid",
                    "description": "Map tranid to program; optional mapset/commarea labels.",
                    "template": """flowchart LR
  subgraph {{ data.region }}
  {% for t in data.transactions %}
  {{ t.tranid }}([{{ t.tranid }}]) --> {{ t.program | replace("-", "_") }}([{{ t.program }}])
  {% endfor %}
  end"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "data.er",
                    "title": "Logical ER Diagram",
                    "view": "er",
                    "language": "mermaid",
                    "description": "Render logical entities and fields as Mermaid ER.",
                    "template": """erDiagram
  {% for e in data.logical %}
  {{ e.name }} {
    {% for f in e.fields %}{{ f.type | replace(" ", "_") }} {{ f.name }}
    {% endfor %}
  }
  {% endfor %}"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "terms.mindmap",
                    "title": "Terms Mindmap",
                    "view": "mindmap",
                    "language": "mermaid",
                    "description": "Terms with aliases as child leaves.",
                    "template": """mindmap
  root((Data Dictionary))
  {% for t in data.terms %}
  {{ t.term }}
    {% for a in (t.aliases or []) %}{{ a }}
    {% endfor %}
  {% endfor %}"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "lineage.graph",
                    "title": "Lineage Graph",
                    "view": "flowchart",
                    "language": "mermaid",
                    "description": "Show lineage edges as a directed graph.",
                    "prompt": {
                        "system": "Render lineage edges as a Mermaid flowchart LR. Use succinct node ids; collapse duplicate edges; annotate edges with op (READ/WRITE/TRANSFORM).",
                        "strict_text": True
                    },
                    "renderer_hints": {"direction": "LR"}
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "inventory.mindmap",
                    "title": "Service/Asset Inventory Mindmap",
                    "view": "mindmap",
                    "language": "mermaid",
                    "description": "Top-level inventory grouped by artifact class.",
                    "template": """mindmap
  root((Inventory))
    Programs
      {% for p in data.programs %}{{ p }}
      {% endfor %}
    Jobs
      {% for j in data.jobs %}{{ j }}
      {% endfor %}
    Datasets
      {% for d in data.datasets %}{{ d }}
      {% endfor %}
    Transactions
      {% for t in data.transactions %}{{ t }}
      {% endfor %}"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "deps.callgraph",
                    "title": "Program Call Graph",
                    "view": "flowchart",
                    "language": "mermaid",
                    "description": "Static call edges across programs.",
                    "prompt": {
                        "system": "Render call_graph as Mermaid graph LR with from --> to. Merge duplicates. Mark dynamic edges with dotted style.",
                        "strict_text": True
                    },
                    "renderer_hints": {"direction": "LR"}
                },
                {
                    "id": "deps.jobflow",
                    "title": "Job Flow",
                    "view": "flowchart",
                    "language": "mermaid",
                    "description": "Sequential flow of job steps.",
                    "template": """flowchart TD
  {% for e in data.job_flow|sort(attribute='seq') %}
  {{ e.step | replace("-", "_") }}([{{ e.job }}::{{ e.step }}\\n{{ e.program }}])
  {% endfor %}
  {% for e in data.job_flow|sort(attribute='seq') %}
    {% set next = loop.index0 + 1 %}
    {% if next < (data.job_flow|length) %}
  {{ data.job_flow[loop.index0].step | replace("-", "_") }} --> {{ data.job_flow[next].step | replace("-", "_") }}
    {% endif %}
  {% endfor %}"""
                },
                {
                    "id": "deps.dataset",
                    "title": "Dataset Producers/Consumers",
                    "view": "flowchart",
                    "language": "mermaid",
                    "description": "Edges from producers to consumers via dataset nodes.",
                    "template": """flowchart LR
  {% for d in data.dataset_deps %}
  {{ d.producer | replace("-", "_") }} --> {{ d.dataset | replace(".", "_") }}([{{ d.dataset }}]) --> {{ d.consumer | replace("-", "_") }}
  {% endfor %}"""
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "process.activity",
                    "title": "Process Activity Flow",
                    "view": "activity",
                    "language": "mermaid",
                    "description": "Flowchart rendering of nodes and edges; lane shown as subgraph if present.",
                    "template": """flowchart TD
  {% for l in (data.lanes or []) %}
  subgraph lane_{{ l.id }}[{{ l.label }}]
  end
  {% endfor %}
  {% for n in data.nodes %}
  {{ n.id }}([{{ n.label }}])
  {% endfor %}
  {% for e in data.edges %}
  {{ e.from }} -->{% if e.condition %}|{{ e.condition }}|{% endif %} {{ e.to }}
  {% endfor %}"""
                }
            ]
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
            "examples": [{"source_process": "POSTTRAN Batch", "diagram": {"nodes": [], "edges": []}}],
            "diagram_recipes": [
                {
                    "id": "diagram.activity.puml",
                    "title": "PlantUML Activity",
                    "view": "activity",
                    "language": "plantuml",
                    "description": "Render activity JSON via adapter to PlantUML instructions.",
                    "prompt": {
                        "system": "Convert the activity diagram JSON to PlantUML instructions. Keep ids stable; use partitions for lanes if present.",
                        "strict_text": True
                    }
                }
            ]
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
            }],
            "diagram_recipes": [
                {
                    "id": "domain.terms.map",
                    "title": "Domain Terms Map",
                    "view": "mindmap",
                    "language": "mermaid",
                    "description": "Domain terms grouped by kind with aliases.",
                    "template": """mindmap
  root((Domain Dictionary))
  {% set kinds = {"entity":[], "event":[], "metric":[], "policy":[], "other":[]} %}
  {% for e in data.entries %}{% do kinds[e.kind].append(e) %}{% endfor %}
  {% for k, arr in kinds.items() %}
  {{ k | capitalize }}
    {% for e in arr %}{{ e.term }}
      {% for a in (e.aliases or []) %}{{ a }}
      {% endfor %}
    {% endfor %}
  {% endfor %}"""
                }
            ]
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
