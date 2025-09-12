# services/learning-service/app/clients/parser_proleap.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from app.config import settings

logger = logging.getLogger("app.clients.parser_cobol")

BASE = (getattr(settings, "PROLEAP_PARSER_BASE_URL", "http://renova-proleap-cb2xml:8080")).rstrip("/")

DEFAULT_PARSE_PATHS: List[str] = [
    "/parse",
    "/api/v1/parse",
    "/v1/parse",
]

def _safe_json(text: str) -> Dict[str, Any]:
    """
    Try to parse JSON; if it fails, wrap the raw text into a structured shape
    that upstream code can safely handle.
    """
    try:
        return json.loads(text)
    except Exception:
        head = (text or "").strip()[:2000]
        return {"programs": [], "errors": [{"stage": "transport", "message": "non-JSON response", "head": head}]}

def _normalize_parse_response(data: Dict[str, Any]) -> Dict[str, Any]:
    # Ensure keys exist with predictable types
    programs = list(data.get("programs") or [])
    errors = list(data.get("errors") or [])
    meta = data.get("meta") or {}
    return {"programs": programs, "errors": errors, "meta": meta}

def _normalize_copybook_response(data: Dict[str, Any]) -> Dict[str, Any]:
    xmls = list(data.get("xmlDocs") or [])
    errors = list(data.get("errors") or [])
    meta = data.get("meta") or {}
    return {"xmlDocs": xmls, "errors": errors, "meta": meta}

async def _discover_parse_paths(client: httpx.AsyncClient) -> List[str]:
    for ep in ("/openapi.json", "/swagger.json", "/openapi", "/v1/openapi.json"):
        try:
            r = await client.get(f"{BASE}{ep}")
            r.raise_for_status()
            spec = r.json()
        except Exception:
            continue
        try:
            paths = spec.get("paths") or {}
            discovered: List[str] = []
            for path, ops in paths.items():
                if not isinstance(ops, dict):
                    continue
                post_def = ops.get("post") or ops.get("POST")
                if not isinstance(post_def, dict):
                    continue
                op_id = (post_def.get("operationId") or "").lower()
                if ("parse" in (path or "").lower()) or ("parse" in op_id):
                    discovered.append(path if path.startswith("/") else f"/{path}")
            if discovered:
                logger.info("parser.cobol: discovered via openapi %s", discovered)
                return discovered
        except Exception:
            continue
    return []

async def _post_json(client: httpx.AsyncClient, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{BASE}{path}"
    logger.info("parser.cobol -> %s body=%s", url, json.dumps(body, separators=(",", ":")))
    try:
        r = await client.post(url, json=body)
    except httpx.HTTPError as e:
        # Pure transport error: surface as structured error response
        logger.warning("parser.cobol transport error %s: %s", url, e)
        return {"programs": [], "errors": [{"stage": "transport", "message": str(e)}], "meta": {}}

    text = r.text or ""
    if r.status_code >= 400:
        # Parser API may still return JSON detail; normalize either way.
        logger.warning("parser.cobol <- %s status=%s body(head)=%s", url, r.status_code, text[:500])
        data = _safe_json(text)
        # Attach HTTP status context
        data.setdefault("errors", []).append({"stage": "http", "status": r.status_code, "message": "parser returned error"})
        return _normalize_parse_response(data)

    logger.info("parser.cobol <- %s status=%s", url, r.status_code)
    try:
        return _normalize_parse_response(r.json())
    except Exception:
        return _normalize_parse_response(_safe_json(text))

async def parse_sources(*, sources: List[str], dialect: str = "ANSI85") -> Dict[str, Any]:
    body = {"sources": sources, "dialect": dialect}
    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_S) as client:
        try:
            hr = await client.get(f"{BASE}/health")
            logger.info("parser.cobol.health <- %s status=%s", f"{BASE}/health", getattr(hr, "status_code", "?"))
        except Exception:
            pass

        candidates: List[str] = []
        try:
            candidates += await _discover_parse_paths(client)
        except Exception:
            pass

        seen = set()
        ordered = [p for p in candidates if not (p in seen or seen.add(p))]
        for p in DEFAULT_PARSE_PATHS:
            if p not in seen:
                ordered.append(p); seen.add(p)

        last_result: Dict[str, Any] | None = None
        for path in ordered:
            result = await _post_json(client, path, body)
            # If we get any shape back, return immediately; the server encodes its own errors.
            if isinstance(result, dict):
                return result
            last_result = result

    return last_result or {"programs": [], "errors": [{"stage": "client", "message": "parser call failed"}], "meta": {}}

# ───────────────────────── Convenience wrappers expected by tool_runner ─────────────────────────

async def parse_programs(*, program_paths: List[str], dialect: str = "ANSI85") -> Dict[str, Any]:
    sources: List[str] = []
    safe_paths: List[Path] = []
    for p in program_paths or []:
        pp = Path(p)
        try:
            if pp.is_file():
                sources.append(pp.read_text(encoding="utf-8", errors="ignore"))
                safe_paths.append(pp)
        except Exception as e:
            logger.warning("parser.cobol: failed to read %s: %s", p, e)

    if not sources:
        logger.info("parser.cobol: no program sources to parse (0 files)")
        return {"items": [], "errors": [], "meta": {"note": "no sources"}}

    raw = await parse_sources(sources=sources, dialect=dialect)
    programs = list(raw.get("programs") or [])
    errors = list(raw.get("errors") or [])
    meta = raw.get("meta") or {}

    items: List[Dict[str, Any]] = []
    for i, prog in enumerate(programs):
        fallback = safe_paths[i].name if i < len(safe_paths) else f"program{i}"
        name = (prog.get("name")
                or prog.get("program")
                or prog.get("id")
                or fallback)
        items.append({"name": str(name), "data": prog})

    if errors:
        # Log but do not fail—leave decisions to calling node
        logger.warning("parser.cobol: parse reported %d error(s): %s", len(errors), json.dumps(errors[:3]))
    return {"items": items, "errors": errors, "meta": meta}

async def copybook_to_xml(*, copybooks: List[str], encoding: Optional[str] = None) -> Dict[str, Any]:
    body = {"copybooks": copybooks}
    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_S) as client:
        url = f"{BASE}/copybook_to_xml"
        logger.info("parser.cobol -> %s body=%s", url, json.dumps(body, separators=(",", ":")))
        try:
            r = await client.post(url, json=body)
        except httpx.HTTPError as e:
            logger.warning("parser.cobol transport error %s: %s", url, e)
            return {"items": [], "errors": [{"stage": "transport", "message": str(e)}], "meta": {}}

        text = r.text or ""
        if r.status_code >= 400:
            logger.warning("parser.cobol <- %s status=%s body(head)=%s", url, r.status_code, text[:500])
            data = _normalize_copybook_response(_safe_json(text))
        else:
            try:
                data = _normalize_copybook_response(r.json())
            except Exception:
                data = _normalize_copybook_response(_safe_json(text))

    xml_docs = list(data.get("xmlDocs") or [])
    items = [{"name": f"copybook{i}.xml", "data": x} for i, x in enumerate(xml_docs)]
    return {"items": items, "errors": list(data.get("errors") or []), "meta": data.get("meta") or {}}

# Optional stubs (unchanged)
async def paragraph_flow() -> Dict[str, Any]:
    return {}

async def file_mapping() -> Dict[str, Any]:
    return {}

# ───────────────────────── Drop-in helper: read files from landing zone ─────────────────────────

LANDING = getattr(settings, "LANDING_ZONE", "/landing_zone")

def _is_within(child: Path, parent: Path) -> bool:
    try:
        child_r = child.resolve()
        parent_r = parent.resolve()
        return parent_r == child_r or parent_r in child_r.parents
    except Exception:
        return False

def _strip_leading_repo(rel: str) -> str:
    p = Path(rel.lstrip("/"))
    parts = list(p.parts)
    if parts and parts[0] == "repo":
        parts = parts[1:]
    return str(Path(*parts)) if parts else ""

async def parse_workspace_files(
    *,
    workspace: str,
    rel_paths: List[str],
    dialect: str = "ANSI85",
) -> Dict[str, Any]:
    ws_root = Path(LANDING) / workspace
    repo_root = ws_root / "repo"
    paths: List[str] = []

    for rel in rel_paths or []:
        rel_clean = _strip_leading_repo(rel)
        if not rel_clean:
            logger.warning("parser_proleap: skipping empty/invalid relative path: %r", rel)
            continue

        candidates = [
            (repo_root / rel_clean),
            (ws_root / rel.lstrip("/")),
        ]

        picked: Path | None = None
        for cand in candidates:
            try:
                if cand.is_file() and _is_within(cand, ws_root):
                    picked = cand
                    break
            except Exception:
                continue

        if picked is None:
            logger.warning("parser_proleap: file not found in workspace '%s': %s", workspace, rel)
            continue

        paths.append(str(picked))

    if not paths:
        raise RuntimeError("No COBOL files found under the workspace for the given rel_paths.")

    logger.info(
        "parser_proleap: collected %d file(s) from workspace '%s' (repo root: %s)",
        len(paths), workspace, repo_root,
    )
    return await parse_programs(program_paths=paths, dialect=dialect)
