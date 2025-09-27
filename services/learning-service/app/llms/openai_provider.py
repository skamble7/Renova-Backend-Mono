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
    OpenAI provider using Chat Completions.

    - acomplete_text: returns plain string content (e.g., Mermaid).
    - acomplete_json: enforces JSON output and returns parsed dict.
    """

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        default_temperature: float = 0.1,
        default_max_tokens: int = 4000,
        base_url: Optional[str] = None,
    ) -> None:
        if AsyncOpenAI is None:  # pragma: no cover
            raise RuntimeError(
                "openai package not installed. Add 'openai>=1.0.0' to pyproject and set OPENAI_API_KEY."
            )
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")

        # Allow custom base URL if proxying
        base_url = base_url or os.getenv("OPENAI_BASE_URL") or None
        self._client = AsyncOpenAI(api_key=self._api_key, base_url=base_url)

        self._default_model = default_model or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self._default_temperature = float(os.getenv("LLM_TEMPERATURE", str(default_temperature)))
        self._default_max_tokens = int(os.getenv("LLM_MAX_TOKENS", str(default_max_tokens)))

    async def acomplete_text(self, req: LLMRequest) -> str:
        """Get plain text (no JSON parsing). Useful for Mermaid output."""
        model = req.model or self._default_model
        temperature = req.temperature if req.temperature is not None else self._default_temperature
        max_tokens = req.max_tokens or self._default_max_tokens

        system = (req.system_prompt or "").strip() or "You are a precise system that outputs exactly what is asked."
        user = req.user_prompt.strip()

        try:
            # Prefer response_format={"type":"text"} if supported by SDK/server
            try:
                resp = await self._client.chat.completions.create(
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "text"},  # type: ignore[arg-type]
                )
            except Exception:
                # Fallback for older servers that don't accept response_format
                resp = await self._client.chat.completions.create(
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
        except Exception as e:  # pragma: no cover
            raise LLMProtocolError(f"OpenAI API error: {e!r}")

        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise LLMProtocolError("Empty content from model")
        return content

    async def acomplete_json(self, req: LLMRequest) -> Dict[str, Any]:
        """Enforce JSON output and parse it."""
        model = req.model or self._default_model
        temperature = req.temperature if req.temperature is not None else self._default_temperature
        max_tokens = req.max_tokens or self._default_max_tokens

        system = (req.system_prompt or "").strip()
        user = req.user_prompt.strip()

        # Response format
        response_format: Dict[str, Any]
        if req.strict_json and req.json_schema:
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
            # If you call acomplete_json, we still try to return JSON
            response_format = {"type": "json_object"}

        try:
            resp = await self._client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system or "You output ONLY valid JSON."},
                    {"role": "user", "content": user},
                ],
                response_format=response_format,  # type: ignore[arg-type]
            )
        except Exception as e:  # pragma: no cover
            raise LLMProtocolError(f"OpenAI API error: {e!r}")

        try:
            import json
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise ValueError("empty content")
            return json.loads(content)
        except Exception as e:
            raise LLMProtocolError(f"Invalid JSON from model: {e!r}")
