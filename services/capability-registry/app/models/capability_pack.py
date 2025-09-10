#cam.source.checkout_ref and produce the new COBOL/DB2/VSAM kinds
#services/capability-registry/app/models/capability_pack.py
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any, Union, Literal, Annotated

from pydantic import BaseModel, Field

from .integrations import ResourceRef, RuntimePolicy

# ─────────────────────────────────────────────────────────────
# Global Capability (authoritative registry)
# ─────────────────────────────────────────────────────────────
class GlobalCapability(BaseModel):
    id: str = Field(..., description="Stable capability id (e.g., cap.catalog.services)")
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    parameters_schema: Optional[Dict[str, Any]] = None
    produces_kinds: List[str] = Field(default_factory=list)  # must be valid kinds
    requires_kinds: Optional[List[str]] = None               # optional inputs (artifact kinds)
    agent: Optional[str] = None  # e.g., "catalog.services.v1"

class GlobalCapabilityCreate(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    parameters_schema: Optional[Dict[str, Any]] = None
    produces_kinds: List[str] = Field(default_factory=list)
    requires_kinds: Optional[List[str]] = None
    agent: Optional[str] = None

class GlobalCapabilityUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    parameters_schema: Optional[Dict[str, Any]] = None
    produces_kinds: Optional[List[str]] = None
    requires_kinds: Optional[List[str]] = None
    agent: Optional[str] = None

# ─────────────────────────────────────────────────────────────
# Playbook steps (Renova extensions; backward compatible)
# ─────────────────────────────────────────────────────────────
class CapabilityStep(BaseModel):
    type: Literal["capability"] = "capability"
    id: str = Field(..., description="Stable step id (uuid or semantic id)")
    name: str
    capability_id: str = Field(..., description="Global capability id this step invokes")
    description: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    runtime: Optional[RuntimePolicy] = None
    emits: List[str] = Field(default_factory=list)                    # produced artifact kinds (contract)
    requires_kinds: Optional[List[str]] = None                        # required artifact kinds (input contract)
    depends_on_steps: List[str] = Field(default_factory=list)         # explicit step ID predecessors
    on_missing: Literal["fail","skip","warn"] = "fail"                # behavior if requirements unmet

class ToolCallStep(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    id: str = Field(..., description="Stable step id (uuid or semantic id)")
    name: str
    tool_key: str = Field(..., description="Integration tool key, e.g., tool.cobol.parse")
    description: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    resources: List[ResourceRef] = Field(default_factory=list)
    runtime: Optional[RuntimePolicy] = None
    emits: List[str] = Field(default_factory=list)
    requires_kinds: Optional[List[str]] = None
    depends_on_steps: List[str] = Field(default_factory=list)
    on_missing: Literal["fail","skip","warn"] = "fail"

# Discriminated union (pydantic v2)
PlaybookStep = Annotated[Union[CapabilityStep, ToolCallStep], Field(discriminator="type")]

class Playbook(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    steps: List[PlaybookStep] = Field(default_factory=list)
    edges: List[Dict[str, str]] = Field(default_factory=list)   # optional explicit DAG: {"from": step_id, "to": step_id}
    produces: List[str] = Field(default_factory=list)           # overall contract

# Snapshot of GlobalCapability at time of pack (for reproducibility)
class CapabilitySnapshot(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    parameters_schema: Optional[Dict[str, Any]] = None
    produces_kinds: List[str] = Field(default_factory=list)
    requires_kinds: Optional[List[str]] = None
    agent: Optional[str] = None

class CapabilityPack(BaseModel):
    id: str = Field(..., alias="_id")
    key: str
    version: str
    title: str
    description: str  # required
    capability_ids: List[str] = Field(default_factory=list, description="Refs to global capabilities used")
    capabilities: List[CapabilitySnapshot] = Field(default_factory=list, description="Denormalized snapshots")
    playbooks: List[Playbook] = Field(default_factory=list)

    # Renova-only (optional)
    connectors: List[str] = Field(default_factory=list)         # connector keys
    tools: List[str] = Field(default_factory=list)              # tool keys
    default_policies: Dict[str, Any] = Field(default_factory=dict)

    created_at: datetime
    updated_at: datetime

class CapabilityPackCreate(BaseModel):
    key: str
    version: str
    title: str
    description: str  # required
    capability_ids: List[str] = Field(default_factory=list)
    playbooks: List[Playbook] = Field(default_factory=list)
    # optional extras
    connectors: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    default_policies: Dict[str, Any] = Field(default_factory=dict)

class CapabilityPackUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    capability_ids: Optional[List[str]] = None
    playbooks: Optional[List[Playbook]] = None
    connectors: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    default_policies: Optional[Dict[str, Any]] = None
