from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from .integration_models import IntegrationSnapshot


# ─────────────────────────────────────────────────────────────
# LLM configuration (used only when no MCP integration is bound)
# ─────────────────────────────────────────────────────────────
class LLMConfig(BaseModel):
    provider: str = Field(..., description="e.g., openai, azure_openai, anthropic, ollama, local")
    model: str = Field(..., description="Model identifier (e.g., gpt-4.1-mini, o3-mini, llama3.1:8b)")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific params (temperature, max_tokens, seed, top_p, json_mode, etc.)",
    )
    system_override: Optional[str] = Field(
        default=None, description="Optional system prompt override for this capability."
    )
    # kind_id -> schema_version; executor uses this to lock strict JSON outputs
    output_contracts: Dict[str, str] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────
# MCP integration binding at the capability level
# ─────────────────────────────────────────────────────────────
class MCPToolCallSpec(BaseModel):
    """
    Mapping between an MCP tool and the CAM kinds expected as outputs from that call.
    The executor will validate produced artifacts against CAM schemas.
    """
    tool: str = Field(..., description="Exact MCP tool name to invoke on the server.")
    output_kinds: List[str] = Field(
        default_factory=list,
        description="CAM kind ids produced by this tool (one or many).",
    )
    input_schema: Optional[Dict[str, Any]] = Field(
        default=None, description="Optional JSON schema/hints for tool input payload."
    )
    timeout_sec: int = Field(default=60, ge=1, le=3600)
    retries: int = Field(default=1, ge=0)


class MCPIntegrationBinding(BaseModel):
    """
    If present, this capability must rely solely on MCP (no LLM fallback).
    You can bind by snapshot directly to ensure reproducibility at pack time.
    """
    # Either fill snapshot here, or reference an external integration by id
    integration_ref: Optional[str] = Field(
        default=None, description="Reusable integration id (server-side object)."
    )
    integration_snapshot: Optional[IntegrationSnapshot] = Field(
        default=None, description="Frozen snapshot for reproducibility."
    )
    tool_calls: List[MCPToolCallSpec] = Field(
        default_factory=list,
        description="One or more tool calls that together produce the declared kinds.",
    )

    @model_validator(mode="after")
    def _validate_binding(self):
        if not self.integration_ref and not self.integration_snapshot:
            raise ValueError("MCPIntegrationBinding requires integration_ref or integration_snapshot.")
        if self.integration_ref and self.integration_snapshot:
            # Allowing both is ambiguous; keep it strict to avoid drift.
            raise ValueError("Provide either integration_ref or integration_snapshot, not both.")
        if not self.tool_calls:
            raise ValueError("MCPIntegrationBinding.tool_calls must not be empty.")
        return self


# ─────────────────────────────────────────────────────────────
# Global Capability (authoritative registry)
# ─────────────────────────────────────────────────────────────
class GlobalCapability(BaseModel):
    id: str = Field(..., description="Stable capability id (e.g., cap.cobol.copybook.parse)")
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    parameters_schema: Optional[Dict[str, Any]] = Field(
        default=None, description="JSON Schema for step params validation (executor may enforce)."
    )
    produces_kinds: List[str] = Field(
        default_factory=list, description="CAM kind ids produced by this capability."
    )
    agent: Optional[str] = Field(
        default=None, description="Optional semantic hint (e.g., 'copybook.parser.v1')."
    )

    # Renova extensions
    integration: Optional[MCPIntegrationBinding] = None
    llm_config: Optional[LLMConfig] = Field(
        default=None, description="Ignored if 'integration' is present."
    )

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _validate_modes(self):
        if self.integration is not None and self.llm_config is not None:
            raise ValueError("Capability cannot define both MCP 'integration' and 'llm_config'.")
        return self


class GlobalCapabilityCreate(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    parameters_schema: Optional[Dict[str, Any]] = None
    produces_kinds: List[str] = Field(default_factory=list)
    agent: Optional[str] = None
    integration: Optional[MCPIntegrationBinding] = None
    llm_config: Optional[LLMConfig] = None


class GlobalCapabilityUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    parameters_schema: Optional[Dict[str, Any]] = None
    produces_kinds: Optional[List[str]] = None
    agent: Optional[str] = None
    integration: Optional[MCPIntegrationBinding] = None
    llm_config: Optional[LLMConfig] = None
