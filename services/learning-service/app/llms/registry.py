# services/learning-service/app/llms/registry.py
from __future__ import annotations
import os, json, logging
from typing import Any, List, Dict

logger = logging.getLogger("app.llms.registry")

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore


class _NoopProvider:
    async def chat_json(self, messages: List[Dict[str, Any]]) -> str:
        """
        Deterministic, JSON-only fallback used when OPENAI is unavailable.
        - If the user content looks like JSON with "steps", return an identity param override shape.
        - Otherwise return {"issues": []} for validators.
        """
        try:
            last_json_str = next(
                m["content"]
                for m in reversed(messages)
                if isinstance(m.get("content"), str) and m["content"].strip().startswith("{")
            )
            obj = json.loads(last_json_str)
        except Exception:
            obj = {}

        if isinstance(obj, dict) and "steps" in obj:
            return json.dumps(
                {"steps": [{"id": s.get("id"), "params": {}} for s in obj.get("steps", [])]},
                separators=(",", ":"),
            )
        return json.dumps({"issues": []}, separators=(",", ":"))


def _mk_client() -> Any | None:
    if not (os.getenv("OPENAI_API_KEY") and OpenAI):
        return None
    try:
        return OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL") or None,
        )
    except Exception as e:
        logger.warning("OpenAI client init failed: %s", e)
        return None


class _OpenAIProvider:
    """
    Robust JSON caller: tries Responses API (with/without response_format), then Chat Completions
    (with/without response_format). Always returns a JSON string (or "{}").
    """
    def __init__(self):
        self.client = _mk_client()
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _messages_to_chat(self, messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        # Normalize to classic chat format
        chat_msgs: List[Dict[str, str]] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if not isinstance(content, str):
                try:
                    content = json.dumps(content, ensure_ascii=False)
                except Exception:
                    content = str(content)
            chat_msgs.append({"role": role, "content": content})
        return chat_msgs

    async def chat_json(self, messages: List[Dict[str, Any]]) -> str:
        if not self.client:
            return "{}"

        # 1) Try Responses API with response_format
        try:
            resp = self.client.responses.create(
                model=self.model,
                input=messages,
                response_format={"type": "json_object"},
            )
            return getattr(resp, "output_text", "{}") or "{}"
        except TypeError as e:
            # SDK too old for response_format on responses.create
            logger.info("responses.create no response_format support; falling back (%s)", e)
        except Exception as e:
            logger.debug("responses.create with response_format failed: %s", e)

        # 2) Try Responses API without response_format
        try:
            resp = self.client.responses.create(model=self.model, input=messages)
            return getattr(resp, "output_text", "{}") or "{}"
        except Exception as e:
            logger.debug("responses.create (no response_format) failed: %s", e)

        # 3) Try Chat Completions with response_format
        chat_msgs = self._messages_to_chat(messages)
        try:
            cc = self.client.chat.completions.create(
                model=self.model,
                messages=chat_msgs,
                response_format={"type": "json_object"},
            )
            content = (cc.choices[0].message.content if cc and cc.choices else "") or ""
            return content if content.strip() else "{}"
        except TypeError as e:
            logger.info("chat.completions.create no response_format support; falling back (%s)", e)
        except Exception as e:
            logger.debug("chat.completions.create (json) failed: %s", e)

        # 4) Chat Completions without response_format (prompt the model to output JSON)
        try:
            # Append a tiny “return JSON only” hint
            hint = {"role": "system", "content": "Return ONLY valid JSON (no prose)."}
            cc = self.client.chat.completions.create(
                model=self.model,
                messages=[hint, *chat_msgs],
            )
            content = (cc.choices[0].message.content if cc and cc.choices else "") or ""
            # Best-effort sanitize to JSON
            try:
                json.loads(content)
                return content
            except Exception:
                # Try to extract the last {...} block
                import re
                m = re.findall(r"\{[\s\S]*\}", content)
                if m:
                    try:
                        json.loads(m[-1])
                        return m[-1]
                    except Exception:
                        pass
            return "{}"
        except Exception as e:
            logger.error("chat.completions.create failed: %s", e)
            return "{}"


def get_provider(model_id: str | None) -> Any:
    if os.getenv("OPENAI_API_KEY") and OpenAI:
        return _OpenAIProvider()
    return _NoopProvider()
