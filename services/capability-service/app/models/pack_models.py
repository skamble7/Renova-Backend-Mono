from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .capability_models import LLMConfig, MCPIntegrationBinding


# ─────────────────────────────────────────────────────────────
# Playbooks
# ─────────────────────────────────────────────────────────────
class PlaybookStep(BaseModel):
    id: str = Field(..., description="Stable step id (uuid or semantic id).")
    name: str
    capability_id: str = Field(..., description="Global capability id this step invokes.")
    description: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)


class Playbook(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    steps: List[PlaybookStep] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Snapshot of a capability, embedded in a pack for reproducibility
# ─────────────────────────────────────────────────────────────
class CapabilitySnapshot(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    parameters_schema: Optional[Dict[str, Any]] = None
    produces_kinds: List[str] = Field(default_factory=list)
    agent: Optional[str] = None

    # Renova extensions (frozen at pack time)
    integration: Optional[MCPIntegrationBinding] = None
    llm_config: Optional[LLMConfig] = None


class PackStatus(str, Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class CapabilityPack(BaseModel):
    id: str = Field(..., alias="_id")
    key: str
    version: str
    title: str
    description: str

    capability_ids: List[str] = Field(
        default_factory=list,
        description="Refs to global capabilities used by the pack."
    )
    capabilities: List[CapabilitySnapshot] = Field(
        default_factory=list,
        description="Denormalized snapshots for reproducibility."
    )
    playbooks: List[Playbook] = Field(default_factory=list)

    status: PackStatus = PackStatus.draft

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    published_at: Optional[datetime] = None

    created_by: Optional[str] = None
    updated_by: Optional[str] = None

    model_config = dict(populate_by_name=True)


class CapabilityPackCreate(BaseModel):
    key: str
    version: str
    title: str
    description: str
    capability_ids: List[str] = Field(default_factory=list)
    playbooks: List[Playbook] = Field(default_factory=list)


class CapabilityPackUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    capability_ids: Optional[List[str]] = None
    playbooks: Optional[List[Playbook]] = None
    status: Optional[PackStatus] = None
