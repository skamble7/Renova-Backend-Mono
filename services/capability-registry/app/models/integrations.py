#services/capability-registry/app/models/integrations.py
from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime

class Connector(BaseModel):
    key: str
    type: Literal["parser","indexer","repo","queue","storage","custom"]
    vendor: Optional[str] = None
    version: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    config_schema: Optional[Dict[str, Any]] = None
    secrets: List[str] = Field(default_factory=list)
    doc_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class ConnectorCreate(BaseModel):
    key: str
    type: Literal["parser","indexer","repo","queue","storage","custom"]
    vendor: Optional[str] = None
    version: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    config_schema: Optional[Dict[str, Any]] = None
    secrets: List[str] = Field(default_factory=list)
    doc_url: Optional[str] = None

class ConnectorUpdate(BaseModel):
    type: Optional[str] = None
    vendor: Optional[str] = None
    version: Optional[str] = None
    capabilities: Optional[List[str]] = None
    config_schema: Optional[Dict[str, Any]] = None
    secrets: Optional[List[str]] = None
    doc_url: Optional[str] = None

class ToolSpec(BaseModel):
    key: str                          # e.g., "tool.cobol.parse"
    connector_key: str                # FK -> Connector.key
    operation: str                    # operation name inside the connector
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    produces_kinds: List[str] = Field(default_factory=list)
    requires_kinds: Optional[List[str]] = None                 # <- new: inputs the tool expects
    created_at: datetime
    updated_at: datetime

class ToolCreate(BaseModel):
    key: str
    connector_key: str
    operation: str
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    produces_kinds: List[str] = Field(default_factory=list)
    requires_kinds: Optional[List[str]] = None

class ToolUpdate(BaseModel):
    connector_key: Optional[str] = None
    operation: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    produces_kinds: Optional[List[str]] = None
    requires_kinds: Optional[List[str]] = None

class ResourceRef(BaseModel):
    kind: Literal["repo","bucket","fs","queue","topic","custom"]
    ref: str
    filters: List[str] = Field(default_factory=list)

class RuntimePolicy(BaseModel):
    mode: Literal["external_only","llm","hybrid"] = "hybrid"
    external_required: bool = False
    consensus: Literal["external_over_llm","llm_over_external","majority_vote","cross_check"] = "external_over_llm"
    llm: Optional[Dict[str, Any]] = None  # { temperature, seed, top_p, etc. }

class ExecutionPlan(BaseModel):
    plan_id: str
    pack: Dict[str, str]              # {"key": "...", "version": "..."}
    playbook: Dict[str, Any]          # normalized (id, steps, edges)
    resolved_tools: List[Dict[str, Any]] = Field(default_factory=list)
    policies: Dict[str, Any] = Field(default_factory=dict)
    artifacts_contract: List[str] = Field(default_factory=list)
    # new: report unmet requirements by step for transparency
    unmet_requirements: Dict[str, List[str]] = Field(default_factory=dict)  # {step_id: [kind,...]}
