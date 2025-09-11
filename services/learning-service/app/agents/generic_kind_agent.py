from __future__ import annotations
import os, json, logging
from typing import Any, Dict, Optional

try:
    from openai import OpenAI  # openai>=1.0
except Exception:
    OpenAI = None  # type: ignore

log = logging.getLogger("app.agents.generic_kind_agent")


class GenericKindAgent:
    """
    Matches execute_node's expectation:
      await agent.run(ctx_env, params) -> {"patches":[{"op":"upsert","path":"/artifacts","value":[...]}]}
    If OPENAI is not configured/installed, it returns a deterministic skeleton artifact.
    """

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.enabled = bool(self.api_key and OpenAI)
        self._client = None
        if self.enabled:
            try:
                self._client = OpenAI(api_key=self.api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)
            except Exception as e:
                log.warning("GenericKindAgent OpenAI init failed: %s", e)
                self.enabled = False

    def _call_openai_json(self, system: str, user_payload: dict) -> dict:
        """
        Resilient JSON call across SDK variants.
        """
        if not (self.enabled and self._client):
            return {}

        messages = [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(user_payload)}]

        # 1) responses.create with response_format
        try:
            r = self._client.responses.create(
                model=self.model,
                input=messages,
                response_format={"type": "json_object"},
            )
            txt = getattr(r, "output_text", "") or ""
            return json.loads(txt) if txt else {}
        except TypeError as e:
            log.info("GenericKindAgent: responses.create json_format unsupported; fallback (%s)", e)
        except Exception as e:
            log.debug("GenericKindAgent: responses.create(json) failed: %s", e)

        # 2) responses.create without response_format
        try:
            r = self._client.responses.create(model=self.model, input=messages)
            txt = getattr(r, "output_text", "") or ""
            return json.loads(txt) if txt else {}
        except Exception as e:
            log.debug("GenericKindAgent: responses.create (no json) failed: %s", e)

        # 3) chat.completions with response_format
        try:
            cc = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            txt = (cc.choices[0].message.content if cc and cc.choices else "") or ""
            return json.loads(txt) if txt else {}
        except TypeError as e:
            log.info("GenericKindAgent: chat.completions json_format unsupported; fallback (%s)", e)
        except Exception as e:
            log.debug("GenericKindAgent: chat.completions(json) failed: %s", e)

        # 4) chat.completions plain; ask for JSON only
        try:
            cc = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": "Return ONLY valid JSON."}, *messages],
            )
            txt = (cc.choices[0].message.content if cc and cc.choices else "") or ""
            try:
                return json.loads(txt) if txt else {}
            except Exception:
                import re
                m = re.findall(r"\{[\s\S]*\}", txt)
                if m:
                    try:
                        return json.loads(m[-1])
                    except Exception:
                        pass
        except Exception as e:
            log.error("GenericKindAgent: chat.completions final fallback failed: %s", e)

        return {}

    async def run(self, ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        kind = params.get("kind", "cam.document")
        name = params.get("name") or kind.split(".")[-1].replace("_", " ").title()

        if not self.enabled:
            # No-op, deterministic artifact so downstream steps can proceed.
            artifact = {"kind": kind, "name": name, "data": {"agent": "disabled", "ctx_hint": list(ctx.keys())}}
            return {"patches": [{"op": "upsert", "path": "/artifacts", "value": [artifact]}]}

        # LLM prompt
        system = (
            "You produce a single CAM artifact for the requested 'kind'. "
            "Return ONLY a JSON object with fields {kind,name,data} suitable for storage."
        )
        user = {"kind": kind, "name": name, "context": ctx}

        data = {}
        try:
            data = self._call_openai_json(system, user) or {}
        except Exception as e:
            log.warning("GenericKindAgent: LLM call failed: %s", e)
            data = {}

        artifact = {"kind": data.get("kind", kind), "name": data.get("name", name), "data": data.get("data", {})}
        return {"patches": [{"op": "upsert", "path": "/artifacts", "value": [artifact]}]}
