from __future__ import annotations
import os, json
from typing import Any, Dict, List, Optional

try:
    from openai import OpenAI  # openai>=1.0
except Exception:
    OpenAI = None  # type: ignore

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

        self._client = OpenAI(api_key=self.api_key) if self.enabled else None

    async def run(self, ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        kind = params.get("kind", "cam.document")
        name = params.get("name") or kind.split(".")[-1].replace("_", " ").title()

        if not self.enabled:
            # No-op, deterministic artifact so downstream steps can proceed.
            artifact = {"kind": kind, "name": name, "data": {"agent": "disabled", "ctx_hint": list(ctx.keys())}}
            return {"patches": [{"op": "upsert", "path": "/artifacts", "value": [artifact]}]}

        # LLM: instruct to emit a single artifact for the requested CAM kind
        system = (
            "You produce a single CAM artifact for the requested 'kind'. "
            "Return ONLY a JSON object with fields {kind,name,data} suitable for storage."
        )
        user = json.dumps({"kind": kind, "name": name, "context": ctx}, separators=(",", ":"))

        try:
            resp = self._client.responses.create(
                model=self.model,
                input=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
            )
            try:
                txt = resp.output_text
            except Exception:
                txt = "{}"
            data = json.loads(txt) if txt else {}
        except Exception:
            # Defensive fallback
            data = {"kind": kind, "name": name, "data": {"agent": "error"}}

        # Normalize minimal envelope
        artifact = {"kind": data.get("kind", kind), "name": data.get("name", name), "data": data.get("data", {})}
        return {"patches": [{"op": "upsert", "path": "/artifacts", "value": [artifact]}]}
