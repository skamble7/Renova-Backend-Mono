# services/learning-service/app/agents/registry.py
from __future__ import annotations
from typing import Any
from app.agents.generic_kind_agent import GenericKindAgent

def agent_for_capability(capability_id: str) -> Any:
    # For now, route all capability steps to GenericKindAgent; we drive the 'kind' via step.emits
    return GenericKindAgent()
