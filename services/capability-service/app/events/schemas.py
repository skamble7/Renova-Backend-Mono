# services/capability-service/app/events/schemas.py
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class EventEnvelope(BaseModel):
    """
    Minimal envelope shared across events.
    """
    event: str = Field(..., description="Unversioned event name, e.g., created, updated, published.")
    service: str = Field(..., description="capability|artifact|learning|audit|error")
    org: str = Field(..., description="Tenant/org segment used in routing key.")
    version: str = Field(default="v1", description="Version suffix for RK.")
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    by: Optional[str] = Field(default=None, description="Optional actor/user id")
    payload: Dict[str, Any] = Field(default_factory=dict)


# Thin, explicit payloads for each domain
class CapabilityEvent(BaseModel):
    id: str
    name: str
    produces_kinds: list[str] = Field(default_factory=list)


class PackEvent(BaseModel):
    pack_id: str
    key: str
    version: str
    status: Optional[str] = None


class IntegrationEvent(BaseModel):
    id: str
    name: str
    endpoint: str
