from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class IntegrationAuthRef(BaseModel):
    """
    Reference to credentials; actual secrets are resolved at runtime by the executor.
    """
    method: Literal["none", "bearer", "basic", "api_key"] = "none"
    alias: Optional[str] = Field(
        default=None,
        description="Name/key used by the runtime to look up the secret (e.g., ENV or secret manager).",
    )
    header: Optional[str] = Field(
        default=None,
        description="For api_key/bearer: header name if not Authorization.",
    )
    username_alias: Optional[str] = Field(
        default=None, description="For basic auth: alias to look up username."
    )
    password_alias: Optional[str] = Field(
        default=None, description="For basic auth: alias to look up password."
    )


class MCPIntegration(BaseModel):
    """
    Reusable MCP integration definition (no secrets stored).
    """
    id: str = Field(..., description="Stable integration id (e.g., mcp.cobol.parser)")
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    type: Literal["mcp"] = "mcp"
    endpoint: str = Field(
        ..., description="Endpoint/transport descriptor (e.g., http://host:port, stdio://cmd, ws://...)."
    )
    protocol: Literal["http", "https", "ws", "wss", "stdio", "tcp", "unix"] = "http"
    auth: IntegrationAuthRef = Field(default_factory=IntegrationAuthRef)

    # Optional, informational catalog snapshot returned by validate/probe
    capabilities: Optional[Dict[str, Any]] = Field(
        default=None, description="Server tool catalog snapshot (if known)."
    )

    # Lightweight health metadata (filled by routers/services if you add probes)
    health_last_ok_at: Optional[datetime] = None
    latency_ms_p50: Optional[int] = None
    latency_ms_p95: Optional[int] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntegrationSnapshot(MCPIntegration):
    """
    Snapshot used inside capability snapshots / packs for reproducibility.
    Identical shape to MCPIntegration for simplicity.
    """
    pass
