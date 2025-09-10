# services/artifact-service/app/models/kind_registry.py
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# Prompt specs
# ─────────────────────────────────────────────────────────────

class PromptVariantSpec(BaseModel):
    name: str
    when: Optional[Dict[str, Any]] = None  # e.g., {"stack": "cobol", "flow": "batch"}
    system: Optional[str] = None
    user_template: Optional[str] = None


class PromptSpec(BaseModel):
    # Canonical prompt content for the kind+schema_version
    system: str
    user_template: Optional[str] = None
    variants: List[PromptVariantSpec] = []
    io_hints: Optional[Dict[str, Any]] = None
    strict_json: bool = True
    prompt_rev: int = 1  # non-breaking prompt iterations


# ─────────────────────────────────────────────────────────────
# Identity / normalization / adapters / migrators
# ─────────────────────────────────────────────────────────────

class IdentitySpec(BaseModel):
    # Declarative rules; evaluated by service layer (not DAL)
    natural_key: Optional[Any] = None   # e.g., ["data.program", "data.step"]
    summary_rule: Optional[str] = None  # e.g., "{{data.program}} ({{data.type}})"
    category: Optional[str] = None      # often fixed by kind (e.g., "code")


class AdapterSpec(BaseModel):
    # Adapters normalize miner/LLM output → canonical "data"
    type: Literal["builtin", "dsl"] = "builtin"
    ref: Optional[str] = None
    dsl: Optional[Dict[str, Any]] = None  # optional declarative transform


class MigratorSpec(BaseModel):
    # Version-to-version data migrators (data-only)
    from_version: str
    to_version: str
    type: Literal["builtin", "dsl"] = "builtin"
    ref: Optional[str] = None
    dsl: Optional[Dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────
# Versioned schema entry for a kind
# ─────────────────────────────────────────────────────────────

class SchemaVersionSpec(BaseModel):
    version: str
    json_schema: Dict[str, Any]                 # Draft 2020-12 (data-only)
    additional_props_policy: Literal["forbid", "allow"] = "forbid"
    prompt: PromptSpec
    identity: Optional[IdentitySpec] = None
    adapters: List[AdapterSpec] = []
    migrators: List[MigratorSpec] = []
    examples: List[Dict[str, Any]] = []         # for CI / smoke tests


# ─────────────────────────────────────────────────────────────
# Kind registry documents
# ─────────────────────────────────────────────────────────────

class KindRegistryDoc(BaseModel):
    id: str = Field(alias="_id")               # canonical kind id, e.g. "cam.code.legacy_component"
    title: Optional[str] = None
    summary: Optional[str] = None
    category: Optional[str] = None
    aliases: List[str] = []
    status: Literal["active", "deprecated"] = "active"

    latest_schema_version: str
    schema_versions: List[SchemaVersionSpec]

    policies: Optional[Dict[str, Any]] = None  # retention/visibility/PII/etc.

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KindPluginDoc(BaseModel):
    id: str = Field(alias="_id")               # builtin code id
    type: Literal["adapter", "migrator"]
    # metadata only; actual code is part of the service image
    description: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RegistryMetaDoc(BaseModel):
    id: str = Field(default="meta", alias="_id")
    etag: str                                  # cache-busting token for registry
    registry_version: int = 1                  # monotonically increasing counter
    updated_at: datetime = Field(default_factory=datetime.utcnow)
