from __future__ import annotations

import os
import json
from typing import Any, Dict, Optional, Union

from .base import LLMProvider, LLMRequest, LLMProtocolError

# Optional dependency. We fail with a helpful error if missing.
try:
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore


class OpenAIProvider(LLMProvider):
    """
    OpenAI provider using Chat Completions with optional JSON response constraints.
    - If `strict_json=True`, we attempt to enforce JSON (optionally via a provided schema).
    - If `strict_json=False`, we return the raw text string from the model.
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

    async def _chat(
        self,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        system: str,
        user: str,
        response_format: Dict[str, Any],
    ) -> str:
        """Call chat.completions and return the message content (string)."""
        try:
            resp = await self._client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                messages=[
                    (
                        {"role": "system", "content": system}
                        if system
                        else {"role": "system", "content": "You are a precise system that outputs only valid JSON when asked."}
                    ),
                    {"role": "user", "content": user},
                ],
                # Newer SDKs/Models support response_format for json/text enforcement.
                response_format=response_format,  # type: ignore[arg-type]
            )
        except Exception as e:  # pragma: no cover
            raise LLMProtocolError(f"OpenAI API error: {e!r}")

        content = (resp.choices[0].message.content or "").strip()
        if not content:
            raise LLMProtocolError("Empty completion content from model")
        return content

    def _response_format_for(self, *, strict_json: bool, json_schema: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if strict_json and json_schema:
            # Structured JSON with schema
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": "schema",
                    "schema": json_schema,
                    "strict": True,
                },
            }
        if strict_json:
            # Generic JSON object mode (no schema)
            return {"type": "json_object"}
        # Plain text
        return {"type": "text"}

    async def acomplete_json(self, req: LLMRequest) -> Any:
        """
        Historically returned JSON. Now:
        - If req.strict_json == True: parse and return JSON (dict/list), else raise LLMProtocolError on failure.
        - If req.strict_json == False: return the raw string content (no JSON parsing).
        """
        model = req.model or self._default_model
        temperature = req.temperature if req.temperature is not None else self._default_temperature
        max_tokens = req.max_tokens or self._default_max_tokens

        system = (req.system_prompt or "").strip()
        user = req.user_prompt.strip()

        response_format = self._response_format_for(strict_json=req.strict_json, json_schema=req.json_schema)
        content = await self._chat(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
            user=user,
            response_format=response_format,
        )

        # If caller asked for text (strict_json=False), just return the raw text.
        if not req.strict_json:
            return content

        # Otherwise, parse JSON strictly.
        try:
            return json.loads(content)
        except Exception as e:
            raise LLMProtocolError(f"Invalid JSON from model: {e!r}")

    async def acomplete_text(self, req: LLMRequest) -> str:
        """
        Always return raw text. Ignores req.strict_json and req.json_schema.
        Useful for prompts that expect Mermaid, code, or other non-JSON output.
        """
        model = req.model or self._default_model
        temperature = req.temperature if req.temperature is not None else self._default_temperature
        max_tokens = req.max_tokens or self._default_max_tokens

        system = (req.system_prompt or "").strip()
        user = req.user_prompt.strip()

        content = await self._chat(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
            user=user,
            response_format={"type": "text"},
        )
        return content
