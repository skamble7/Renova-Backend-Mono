from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


class LLMProtocolError(RuntimeError):
    """Raised when the provider returns an unusable response (non-JSON, empty, etc.)."""


@dataclass
class LLMRequest:
    """
    A normalized request the agent can issue to any provider.
    """
    system_prompt: Optional[str]
    user_prompt: str
    json_schema: Optional[Dict[str, Any]] = None
    model: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 4000
    strict_json: bool = True
    extra: Dict[str, Any] = None  # provider-specific kwargs


class LLMProvider(ABC):
    """
    Provider SPI: implement a strict-JSON completion call.
    """

    @abstractmethod
    async def acomplete_json(self, req: LLMRequest) -> Dict[str, Any]:
        """
        Return a parsed JSON object conforming to req.json_schema (if provided).
        Implementations should raise LLMProtocolError on failure.
        """
        raise NotImplementedError
