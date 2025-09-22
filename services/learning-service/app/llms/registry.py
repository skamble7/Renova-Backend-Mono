from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from .base import LLMProvider, LLMRequest
from .openai_provider import OpenAIProvider


def build_provider_from_llm_config(llm_config: Optional[Dict[str, Any]]) -> Tuple[LLMProvider, Dict[str, Any]]:
    """
    Given a capability's llm_config (snapshot), return a provider instance and
    a default 'request kwargs' dict to apply when calling it.

    Expected llm_config shape (loosely):
      {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "parameters": { "temperature": 0.1, "max_tokens": 4000 }
      }
    """
    provider_name = (llm_config or {}).get("provider") or "openai"
    model = (llm_config or {}).get("model") or os.getenv("LLM_MODEL", "gpt-4o-mini")
    params = (llm_config or {}).get("parameters") or {}
    temperature = float(params.get("temperature", float(os.getenv("LLM_TEMPERATURE", "0.1"))))
    max_tokens = int(params.get("max_tokens", int(os.getenv("LLM_MAX_TOKENS", "4000"))))

    if provider_name.lower() == "openai":
        provider = OpenAIProvider(default_model=model, default_temperature=temperature, default_max_tokens=max_tokens)
        default_req_kwargs = {"model": model, "temperature": temperature, "max_tokens": max_tokens}
        return provider, default_req_kwargs

    raise ValueError(f"Unsupported LLM provider: {provider_name}")
