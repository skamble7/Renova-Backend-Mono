# services/learning-service/app/agents/spi.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Protocol


# ─────────────────────────────────────────────────────────────
# Execution SPI (interfaces used inside nodes)
# ─────────────────────────────────────────────────────────────

class MCPInvoker(Protocol):
    async def call_tool(
        self,
        tool: str,
        args: Dict[str, Any],
        *,
        timeout_sec: Optional[float] = None,
        retries: int = 0,
        correlation_id: Optional[str] = None,
    ) -> Any: ...


class LLMCaller(Protocol):
    async def acomplete_json(self, req: "LLMRequest") -> Dict[str, Any]: ...


# ─────────────────────────────────────────────────────────────
# Lightweight request object for LLM calls
# (re-exported from llms.base if you prefer; duplicated here to keep SPI minimal)
# ─────────────────────────────────────────────────────────────
@dataclass
class LLMRequest:
    system_prompt: Optional[str]
    user_prompt: str
    json_schema: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 4000
    strict_json: bool = True
    extra: Dict[str, Any] = None


# ─────────────────────────────────────────────────────────────
# Planning structures (per-step execution plan)
# ─────────────────────────────────────────────────────────────

@dataclass
class StepPlan:
    step_id: str
    name: str
    capability_id: str
    mode: Literal["mcp", "llm"]
    produces_kinds: List[str]
    tool_calls: List[Dict[str, Any]]  # for MCP: [{tool, timeout_sec?, retries?, args?}]
    capability_snapshot: Dict[str, Any]  # resolved snapshot (incl. integration or llm_config)
