from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union, Annotated

from pydantic import BaseModel, Field, AnyUrl


# ─────────────────────────────────────────────────────────────
# Auth (HTTP-only)
# ─────────────────────────────────────────────────────────────
class IntegrationAuthRef(BaseModel):
    """
    Reference to credentials; actual secrets are resolved at runtime by the executor.
    """
    method: Literal["none", "bearer", "basic", "api_key"] = "none"

    # Secret aliases (resolved by runtime; never store raw secrets here)
    alias: Optional[str] = Field(
        default=None,
        description="For bearer/api_key: alias for token/api key (resolved at runtime).",
    )
    username_alias: Optional[str] = Field(
        default=None,
        description="For basic auth: alias to look up username."
    )
    password_alias: Optional[str] = Field(
        default=None,
        description="For basic auth: alias to look up password."
    )

    # Headers
    header: Optional[str] = Field(
        default=None,
        description="For api_key/bearer: header name if not Authorization.",
    )


# ─────────────────────────────────────────────────────────────
# Transports
# ─────────────────────────────────────────────────────────────
class HTTPTransport(BaseModel):
    """
    MCP over HTTP/HTTPS (or WS variants if you extend later).
    """
    kind: Literal["http"]
    base_url: Union[AnyUrl, str] = Field(..., description="e.g., http://host:7101")
    headers: Dict[str, str] = Field(default_factory=dict, description="Static headers (non-secret values).")
    auth: IntegrationAuthRef = Field(default_factory=IntegrationAuthRef)
    timeout_sec: int = Field(default=60, ge=1, le=600)
    verify_tls: bool = Field(default=True, description="Only meaningful for https.")
    retry_max_attempts: int = Field(default=2, ge=0, le=10)
    retry_backoff_ms: int = Field(default=250, ge=0, le=30_000)


class StdioTransport(BaseModel):
    """
    MCP over STDIO (spawn a local process and talk over stdin/stdout).
    """
    kind: Literal["stdio"]
    command: str = Field(..., description="Executable path or command name.")
    args: List[str] = Field(default_factory=list)
    cwd: Optional[str] = Field(default=None, description="Working directory for the process.")
    # Non-secret env values can be provided inline; secret values should be aliases resolved by the executor.
    env: Dict[str, str] = Field(default_factory=dict, description="Static environment variables (non-secret).")
    env_aliases: Dict[str, str] = Field(
        default_factory=dict,
        description="key -> secret alias (executor resolves to actual value)."
    )
    restart_on_exit: bool = Field(default=False)
    readiness_regex: Optional[str] = Field(
        default=None,
        description="Optional regex to detect server readiness from stdout/stderr."
    )
    kill_timeout_sec: int = Field(default=10, ge=1, le=120)


Transport = Annotated[Union[HTTPTransport, StdioTransport], Field(discriminator="kind")]


# ─────────────────────────────────────────────────────────────
# Integration (reusable)
# ─────────────────────────────────────────────────────────────
class MCPIntegration(BaseModel):
    """
    Reusable MCP integration definition (no secrets stored).
    Explicit transport: either HTTP or STDIO.
    """
    id: str = Field(..., description="Stable integration id (e.g., mcp.cobol.parser)")
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    type: Literal["mcp"] = "mcp"
    transport: Transport

    # Optional, informational catalog snapshot returned by validate/probe
    capabilities: Optional[Dict[str, Any]] = Field(
        default=None, description="Server tool catalog snapshot (if known)."
    )

    # Lightweight health metadata (may be set by a probe endpoint)
    health_last_ok_at: Optional[datetime] = None
    latency_ms_p50: Optional[int] = None
    latency_ms_p95: Optional[int] = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IntegrationSnapshot(MCPIntegration):
    """
    Snapshot used inside capability snapshots/packs for reproducibility.
    Identical shape to MCPIntegration for simplicity.
    """
    pass
