# services/learning-service/app/agents/generic_kind_agent.py
from __future__ import annotations
import os, json, logging, re
from typing import Any, Dict, Optional, List, Tuple

try:
    from openai import OpenAI  # openai>=1.0
except Exception:
    OpenAI = None  # type: ignore

from app.clients import artifact_service  # fetch kind registry docs

log = logging.getLogger("app.agents.generic_kind_agent")

# --- Env toggles --------------------------------------------------------------
LOG_LLM_IO = os.getenv("LOG_LLM_IO", "1") == "1"              # log prompts/outputs
LOG_LLM_FULL_CTX = os.getenv("LOG_LLM_FULL_CTX", "0") == "1"  # log full context (noisy)
MAX_ARTIFACTS_IN_PROMPT = int(os.getenv("AGENT_MAX_ARTIFACTS", "40"))
MAX_DATA_CHARS = int(os.getenv("AGENT_MAX_DATA_CHARS", "1200"))

# --- Kind prioritization (programs > analysis > source noise) ----------------
_KIND_WEIGHTS = {
    "cam.cobol.program": 100,
    "cam.db2.table_usage": 90,
    "cam.jcl.job": 80,
    "cam.jcl.step": 70,
    "cam.source.repository": 30,
    "cam.source.manifest": 25,
    "cam.source.file": 5,
}
# Allow overrides via env JSON (e.g. {"cam.source.file":1})
_KINDS_WEIGHTED = dict(_KIND_WEIGHTS)
try:
    _kw_env = os.getenv("AGENT_KIND_WEIGHTS_JSON")
    if _kw_env:
        kw = json.loads(_kw_env)
        if isinstance(kw, dict):
            for kk, vv in kw.items():
                _KINDS_WEIGHTED[kk] = int(vv)
except Exception:
    pass

JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


# --- small helpers ------------------------------------------------------------
def _jdump(obj: Any, *, max_chars: int = 8000) -> str:
    """JSON-dump with truncation so logs always show content in message text."""
    try:
        s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        try:
            s = str(obj)
        except Exception:
            s = "<unserializable>"
    return s if len(s) <= max_chars else s[:max_chars] + f"...(+{len(s)-max_chars} chars)"


# --- compaction / summarization ----------------------------------------------
def _shrink_items_prioritized(
    items: List[dict],
    max_items: int = MAX_ARTIFACTS_IN_PROMPT,
    keep_keys: Tuple[str, ...] = ("kind", "name", "data"),
) -> List[dict]:
    """
    Prioritize high-signal kinds over noisy source files.
    Keep data as a preview (keys/len) to stay within token budget.
    """
    # Sort by weight desc; stable among equals
    sorted_items = sorted(
        [a for a in (items or []) if isinstance(a, dict)],
        key=lambda a: _KINDS_WEIGHTED.get(a.get("kind", ""), 10),
        reverse=True,
    )

    out: List[dict] = []
    for a in sorted_items[:max_items]:
        slim = {}
        for k in keep_keys:
            if k not in a:
                continue
            v = a[k]
            if k == "data" and isinstance(v, (dict, list)):
                try:
                    if isinstance(v, dict):
                        slim[k] = {"_keys": list(v.keys())[:30]}
                    else:
                        slim[k] = {"_len": len(v)}
                except Exception:
                    slim[k] = {}
            else:
                slim[k] = v
        out.append(slim)
    return out


def _summarize_related(rel: Dict[str, Any]) -> Dict[str, Any]:
    hard = rel.get("hard") or {}
    soft = rel.get("soft") or {}

    def _map(d: Dict[str, List[dict]]) -> Dict[str, Any]:
        return {k: _shrink_items_prioritized(v) for k, v in (d or {}).items()}

    return {"hard": _map(hard), "soft": _map(soft)}


def _summarize_tool_outputs(touts: Dict[str, Any], max_steps: int = 8) -> Dict[str, Any]:
    """
    Accepts either:
      { step_id: {tool_key, count, emitted_kinds} }  (current)
      or older shape:
      { step_id: {tool_key, artifacts_count, artifacts_kinds} }
    """
    view: Dict[str, Any] = {}
    for sid, env in list((touts or {}).items())[:max_steps]:
        if not isinstance(env, dict):
            continue
        count = env.get("count", env.get("artifacts_count"))
        kinds = env.get("emitted_kinds", env.get("artifacts_kinds"))
        view[sid] = {
            "tool_key": env.get("tool_key"),
            "count": count,
            "emitted_kinds": kinds,
        }
    return view


# --- output shaping -----------------------------------------------------------
def _ensure_artifact_shape(candidate: Dict[str, Any], *, kind_fallback: str, name_fallback: str) -> Dict[str, Any]:
    """Make sure the LLM output has {kind,name,data} with sane types."""
    out: Dict[str, Any] = {}
    try:
        if not isinstance(candidate, dict):
            candidate = {}
        out["kind"] = str(candidate.get("kind") or kind_fallback)
        out["name"] = str(candidate.get("name") or name_fallback)
        data = candidate.get("data")
        if not isinstance(data, dict):
            if isinstance(data, list):
                out["data"] = {"_list": data}
            elif data is None:
                out["data"] = {}
            else:
                out["data"] = {"_value": data}
        else:
            out["data"] = data
    except Exception as e:
        log.debug("ensure_artifact_shape: coercion failed: %s", e)
        out = {"kind": kind_fallback, "name": name_fallback, "data": {}}
    return out


def _extract_json_safely(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    # OpenAI SDK objects
    try:
        txt = getattr(payload, "output_text", None)
        if isinstance(txt, str) and txt.strip():
            try: return json.loads(txt)
            except Exception: pass
        choices = getattr(payload, "choices", None)
        if choices:
            try:
                msg = getattr(choices[0], "message", None)
                txt2 = getattr(msg, "content", None) if msg else None
                if isinstance(txt2, str) and txt2.strip():
                    try: return json.loads(txt2)
                    except Exception: pass
            except Exception:
                pass
    except Exception:
        pass
    if isinstance(payload, str):
        s = payload.strip()
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            m = JSON_OBJECT_RE.findall(s)
            if m:
                for blob in reversed(m):
                    try: return json.loads(blob)
                    except Exception: continue
            return {}
    if isinstance(payload, list):
        return {"_list": payload}
    if payload is None:
        return {}
    return {"_value": payload}


def _coerce_to_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    Lightweight schema enforcement for common cases.
    """
    if not (isinstance(data, dict) and isinstance(schema, dict)):
        return data if isinstance(data, dict) else {}

    if schema.get("type") != "object":
        return data

    props = schema.get("properties") or {}
    required = list(schema.get("required") or [])
    allow_extra = schema.get("additionalProperties", True) not in (False, "false", "False")

    out: Dict[str, Any] = {}
    # keep only known props if additionalProperties is false
    for k, v in (data or {}).items():
        if (k in props) or allow_extra:
            out[k] = v

    # ensure required
    for rk in required:
        if rk not in out:
            pt = (props.get(rk) or {}).get("type")
            if pt == "array":
                out[rk] = []
            elif pt == "object":
                out[rk] = {}
            elif pt in ("number", "integer"):
                out[rk] = 0
            else:
                out[rk] = ""

    # light type coercion
    for k, p in props.items():
        if k not in out:
            continue
        pt = p.get("type")
        v = out[k]
        try:
            if pt == "array" and not isinstance(v, list):
                out[k] = [v] if v not in (None, "", []) else []
            elif pt == "object" and not isinstance(v, dict):
                out[k] = {}
            elif pt == "string" and not isinstance(v, str):
                out[k] = "" if v is None else str(v)
            elif pt in ("number", "integer"):
                if not isinstance(v, (int, float)):
                    out[k] = 0
        except Exception:
            pass
    return out


# --- kind registry helpers ----------------------------------------------------
async def _fetch_kind_doc(kind_key: str) -> Dict[str, Any]:
    try:
        resp = await artifact_service.get_kinds_by_keys([kind_key])
        if isinstance(resp, dict):
            for it in (resp.get("items") or []):
                kid = it.get("_id") or it.get("id")
                if str(kid) == kind_key:
                    return it
    except Exception as e:
        log.info("GenericKindAgent: kind registry fetch failed: %s", e)
    return {}


def _pick_latest_schema(kind_doc: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (json_schema, prompt_bundle) for latest_schema_version, else ({},{})"""
    if not isinstance(kind_doc, dict):
        return {}, {}
    svs = list(kind_doc.get("schema_versions") or [])
    if not svs:
        return {}, {}
    latest = str(kind_doc.get("latest_schema_version") or "")
    pick = next((sv for sv in svs if str(sv.get("version")) == latest), svs[0])
    json_schema = pick.get("json_schema") or {}
    prompt = pick.get("prompt") or {}
    return json_schema, prompt


def _derive_hints(artifacts: List[dict]) -> Dict[str, Any]:
    programs = [a.get("name") for a in artifacts if a.get("kind") == "cam.cobol.program" and isinstance(a.get("name"), str)]
    files = [a.get("name") for a in artifacts if a.get("kind") == "cam.source.file" and isinstance(a.get("name"), str)]
    return {"program_names": programs[:50], "file_samples": files[:20]}


# --- Agent --------------------------------------------------------------------
class GenericKindAgent:
    """
    Produces a single CAM artifact for the requested 'kind', using the Kind Registry schema + prompt.
    """

    def __init__(self, model: Optional[str] = None):
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.enabled = bool(self.api_key and OpenAI)
        self._client = None
        if self.enabled:
            try:
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=os.getenv("OPENAI_BASE_URL") or None,
                )
            except Exception as e:
                log.warning("GenericKindAgent OpenAI init failed: %s", e)
                self.enabled = False

    def _chat_json(self, system: str, user_payload: dict) -> dict:
        """
        Chat Completions w/ JSON mode → fallback to plain chat + JSON extraction.
        Logs request/response TEXT in the log message (not via 'extra').
        """
        if not (self.enabled and self._client):
            return {}

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, separators=(",", ":"))},
        ]

        if LOG_LLM_IO:
            # log concise request snapshot directly in message text
            req_view = user_payload if LOG_LLM_FULL_CTX else {
                "kind": user_payload.get("kind"),
                "name": user_payload.get("name"),
            }
            log.info("GenericKindAgent.chat_json.request %s", _jdump({"model": self.model, "system": system, "user": req_view}))

        # Path 1: JSON mode
        try:
            cc = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=2048,
            )
            txt = (cc.choices[0].message.content if cc and cc.choices else "") or ""
            if LOG_LLM_IO:
                log.info("GenericKindAgent.chat_json.raw_text %s", _jdump({"text": txt}))
            if txt:
                return json.loads(txt)
        except TypeError as e:
            log.info("GenericKindAgent: chat.completions json_format unsupported; fallback (%s)", e)
        except Exception as e:
            log.debug("GenericKindAgent: chat.completions(json) failed: %s", e)

        # Path 2: Plain chat (strict JSON instruction)
        try:
            strict_messages = [
                {"role": "system", "content": "Return ONLY a valid JSON object. Do not include markdown or prose."},
                *messages,
            ]
            cc = self._client.chat.completions.create(
                model=self.model,
                messages=strict_messages,
                temperature=0,
                max_tokens=2048,
            )
            txt = (cc.choices[0].message.content if cc and cc.choices else "") or ""
            if LOG_LLM_IO:
                log.info("GenericKindAgent.chat_json.raw_text %s", _jdump({"text": txt}))
            if not txt:
                return {}
            try:
                return json.loads(txt)
            except Exception:
                m = re.findall(r"\{[\s\S]*\}", txt)
                if m:
                    for blob in reversed(m):
                        try:
                            return json.loads(blob)
                        except Exception:
                            continue
        except Exception as e:
            log.error("GenericKindAgent: chat.completions fallback failed: %s", e)

        return {}

    async def run(self, ctx: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
        kind = params.get("kind", "cam.document")
        name = params.get("name") or kind.split(".")[-1].replace("_", " ").title()

        # Pull latest schema/prompt for this kind (best effort)
        kind_doc = await _fetch_kind_doc(kind)
        json_schema, prompt_bundle = _pick_latest_schema(kind_doc)

        # Build a trimmed, prioritized context
        all_items: List[dict] = list(((ctx.get("artifacts") or {}).get("items")) or [])
        trimmed_items = _shrink_items_prioritized(all_items)
        ctx_hint = (ctx.get("context_hint") or "").strip()
        trimmed = {
            "avc": ctx.get("avc") or {},
            "fss": ctx.get("fss") or {},
            "pss": ctx.get("pss") or {},
            "artifacts": {"items": trimmed_items},
            "related": _summarize_related(ctx.get("related") or {}),
            "derived": _derive_hints(all_items),
            "context_hint": ctx_hint,
            "tool_outputs": _summarize_tool_outputs(ctx.get("tool_outputs") or {}),
            "schema": json_schema or {},  # give the model the JSON Schema
            # Give the model an explicit target to reduce "creative" kinds:
            "expected": {"kind": kind, "name": name},
        }

        if LOG_LLM_IO:
            # concise state snapshot in message text
            try:
                log.info(
                    "GenericKindAgent.run.state %s",
                    _jdump({
                        "kind": kind,
                        "name": name,
                        "trimmed_artifacts_count": len(trimmed_items),
                        "derived": trimmed.get("derived"),
                        "has_schema": bool(json_schema),
                    }),
                )
            except Exception:
                pass

        if not self.enabled:
            artifact = {
                "kind": kind,
                "name": name,
                "data": {
                    "agent": "disabled",
                    "context_hint_present": bool(ctx_hint),
                    "inputs": {"program_names": trimmed.get("derived", {}).get("program_names", [])},
                },
            }
            log.info("GenericKindAgent.run.artifact %s", _jdump(artifact))
            return {"patches": [{"op": "upsert", "path": "/artifacts", "value": [artifact]}]}

        # System prompt
        base_system = (
            "You are a CAM artifact synthesis agent. Produce exactly one artifact {kind,name,data}.\n"
            f"TOP-LEVEL FIELDS MUST BE: kind='{kind}', name='{name}'.\n"
            "Return ONLY a JSON object. No markdown, no comments."
        )
        registry_sys = (prompt_bundle.get("system") or "").strip() if isinstance(prompt_bundle, dict) else ""
        if json_schema:
            system = ((registry_sys + "\n") if registry_sys else "") + base_system + "\n" + \
                     "The 'data' field MUST conform EXACTLY to this JSON Schema (no extra keys):\n" + \
                     json.dumps(json_schema, ensure_ascii=False)
        else:
            system = ((registry_sys + "\n") if registry_sys else "") + base_system + "\n" + \
                     "If no JSON Schema is provided, still produce minimal valid data with required fields."

        user = {"kind": kind, "name": name, "context": trimmed}

        # LLM call
        raw_out: Dict[str, Any] = {}
        try:
            raw_out = self._chat_json(system, user) or {}
        except Exception as e:
            log.warning("GenericKindAgent: LLM call failed: %s", e)
            raw_out = {}

        if LOG_LLM_IO:
            log.info("GenericKindAgent.run.output %s", _jdump(raw_out))

        # Normalize artifact shape
        artifact_obj = _ensure_artifact_shape(raw_out, kind_fallback=kind, name_fallback=name)

        # --- HARD PIN the top-level kind/name to the requested ones ---
        if artifact_obj.get("kind") != kind or artifact_obj.get("name") != name:
            log.info(
                "GenericKindAgent.run.kind_override %s",
                _jdump({
                    "requested_kind": kind,
                    "requested_name": name,
                    "model_kind": artifact_obj.get("kind"),
                    "model_name": artifact_obj.get("name"),
                }),
            )
        artifact_obj["kind"] = kind
        artifact_obj["name"] = name
        # ---------------------------------------------------------------

        # Post-enforce schema (filter extras, fill required)
        if json_schema and isinstance(artifact_obj.get("data"), dict):
            artifact_obj["data"] = _coerce_to_schema(artifact_obj["data"], json_schema)

        if LOG_LLM_IO:
            log.info("GenericKindAgent.run.artifact %s", _jdump(artifact_obj))

        return {"patches": [{"op": "upsert", "path": "/artifacts", "value": [artifact_obj]}]}
