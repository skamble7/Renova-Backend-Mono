from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .base import LLMProvider, LLMRequest, LLMProtocolError

# Optional dependency. We fail with a helpful error if missing.
try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore


class OpenAIProvider(LLMProvider):
    """
    OpenAI provider using Chat Completions with JSON response constraints.
    This keeps compatibility high; you can switch to Responses API later if preferred.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        default_temperature: float = 0.1,
        default_max_tokens: int = 4000,
    ) -> None:
        if AsyncOpenAI is None:  # pragma: no cover
            raise RuntimeError(
                "openai package not installed. Add 'openai>=1.0.0' to pyproject and set OPENAI_API_KEY."
            )
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._client = AsyncOpenAI(api_key=self._api_key)
        self._default_model = default_model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self._default_temperature = float(os.getenv("LLM_TEMPERATURE", str(default_temperature)))
        self._default_max_tokens = int(os.getenv("LLM_MAX_TOKENS", str(default_max_tokens)))

    async def acomplete_json(self, req: LLMRequest) -> Dict[str, Any]:
        model = req.model or self._default_model
        temperature = req.temperature if req.temperature is not None else self._default_temperature
        max_tokens = req.max_tokens or self._default_max_tokens

        # Messages
        system = (req.system_prompt or "").strip()
        user = req.user_prompt.strip()

        response_format: Dict[str, Any]
        if req.strict_json and req.json_schema:
            # If the SDK supports schema-based JSON mode, use it.
            # Otherwise, fall back to generic json_object mode.
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "schema",
                    "schema": req.json_schema,
                    "strict": True,
                },
            }
        elif req.strict_json:
            response_format = {"type": "json_object"}
        else:
            response_format = {"type": "text"}

        try:
            # Use Chat Completions; newer SDKs accept response_format
            resp = await self._client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system} if system else {"role": "system", "content": "You are a precise system that outputs only valid JSON when asked."},
                    {"role": "user", "content": user},
                ],
                response_format=response_format,  # type: ignore[arg-type]
            )
        except Exception as e:  # pragma: no cover
            raise LLMProtocolError(f"OpenAI API error: {e!r}")

        try:
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise ValueError("empty content")
            # When response_format enforces JSON, the content should already be JSON.
            import json
            return json.loads(content)
        except Exception as e:
            raise LLMProtocolError(f"Invalid JSON from model: {e!r}")
