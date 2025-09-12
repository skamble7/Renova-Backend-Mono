from __future__ import annotations
import json, logging, re
from typing import Any, Dict, List

log = logging.getLogger("app.nodes.validate_node")
JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

def _extract_json_safely(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        s = payload.strip()
        if not s:
            return {}
        try:
            return json.loads(s)
        except Exception:
            m = JSON_OBJECT_RE.findall(s)
            for blob in reversed(m):
                try:
                    return json.loads(blob)
                except Exception:
                    continue
            return {}
    if isinstance(payload, list):
        return {"_list": payload}
    if payload is None:
        return {}
    return {"_value": payload}

def _kinds(items: List[dict]) -> List[str]:
    return sorted({(a or {}).get("kind", "") for a in items if isinstance(a, dict)})

async def validate_node(content: Any, *, purpose: str = "preview") -> Dict[str, Any]:
    """
    Non-destructive validation: attach a validation report while preserving the
    incoming state. Also logs a concise artifact summary for visibility.
    """
    preview_str = str(content)
    log.info(
        "validate_node.request",
        extra={"purpose": purpose, "raw_content": preview_str[:2000], "type": type(content).__name__},
    )
    try:
        result = _extract_json_safely(content)
    except Exception as e:
        log.warning("validate_node: coercion failed", extra={"error": str(e)})
        result = {}
    ok = isinstance(result, dict)

    # Extra visible summary (if the inbound content is a state dict with artifacts)
    art_cnt = 0
    kinds = []
    if isinstance(content, dict):
        arts = list(content.get("artifacts") or [])
        art_cnt = len(arts)
        kinds = _kinds(arts)
        log.info("validate_node.summary", extra={"artifacts": art_cnt, "kinds": kinds})

    report = {"ok": ok, "purpose": purpose, "preview": result, "raw_type": type(content).__name__,
              "artifacts_count": art_cnt, "kinds": kinds}
    log.info("validate_node.result", extra={"ok": ok, "preview": report})

    if isinstance(content, dict):
        merged = dict(content)
        key = "validation" if "validation" not in merged else "_validation"
        merged[key] = report

        logs = list(merged.get("logs") or [])
        logs.append(f"validate: ok={ok} purpose={purpose} artifacts={art_cnt} kinds={kinds}")
        merged["logs"] = logs
        return merged

    return {"validation": report, "content": content, "logs": [f"validate: ok={ok} purpose={purpose} artifacts={art_cnt} kinds={kinds}"]}
    