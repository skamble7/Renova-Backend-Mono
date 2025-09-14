from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .pack_models import Playbook
from .capability_models import MCPToolCallSpec


ExecutionMode = Literal["mcp", "llm"]


class ResolvedPlaybookStep(BaseModel):
    """
    Read-optimized projection for executors or UI previews.
    Capability-service may populate 'produces_kinds' from snapshots;
    'required_kinds' is typically computed by learning-service using CAM.
    """
    id: str
    name: str
    capability_id: str
    params: dict = Field(default_factory=dict)

    execution_mode: ExecutionMode
    produces_kinds: List[str] = Field(default_factory=list)
    required_kinds: List[str] = Field(default_factory=list)  # derived via CAM in learning-service
    tool_calls: Optional[List[MCPToolCallSpec]] = None       # only in MCP mode


class ResolvedPlaybook(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    steps: List[ResolvedPlaybookStep] = Field(default_factory=list)


class ResolvedPackView(BaseModel):
    """
    High-level “resolved” view. The capability-service can serve this
    directly by projecting pack + snapshots (without CAM deps).
    Learning-service can re-emit an augmented view with 'required_kinds'.
    """
    pack_id: str
    key: str
    version: str
    title: str
    description: str
    playbooks: List[ResolvedPlaybook] = Field(default_factory=list)
