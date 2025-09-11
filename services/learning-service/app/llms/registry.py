from __future__ import annotations
import os, json
from typing import Any, List, Dict

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

class _NoopProvider:
    async def chat_json(self, messages: List[Dict[str, Any]]) -> str:
        # Return a safe identity transformation: no param overrides, no issues
        if any(m.get("content","").startswith("{") for m in messages):
            try:
                payload = next(m["content"] for m in messages[::-1] if isinstance(m.get("content"), str) and m["content"].startswith("{"))
                obj = json.loads(payload)
            except Exception:
                obj = {}
            # For planner: keep ids, no overrides; For validator: no issues
            if "steps" in obj:
                return json.dumps({"steps":[{"id": s.get("id"), "params": {}} for s in obj.get("steps",[])]})
            return json.dumps({"issues":[]})
        return json.dumps({"issues":[]})

class _OpenAIProvider:
    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def chat_json(self, messages: List[Dict[str, Any]]) -> str:
        resp = self.client.responses.create(
            model=self.model,
            input=messages,
            response_format={"type": "json_object"},
        )
        try:
            return resp.output_text
        except Exception:
            return "{}"

def get_provider(model_id: str | None) -> Any:
    if os.getenv("OPENAI_API_KEY") and OpenAI:
        return _OpenAIProvider()
    return _NoopProvider()
