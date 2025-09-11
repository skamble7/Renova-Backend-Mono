# services/learning-service/app/clients/parser_proleap.py
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from app.config import settings

# Keep the logger name consistent with earlier logs so you can grep for it
logger = logging.getLogger("app.clients.parser_cobol")

# Base URL for the COBOL parser microservice
BASE = (getattr(settings, "PROLEAP_PARSER_BASE_URL", "http://renova-proleap-cb2xml:8080")).rstrip("/")

# Prefer only the endpoints your service actually implements; remove noisy fallbacks
DEFAULT_PARSE_PATHS: List[str] = [
    "/parse",
    "/api/v1/parse",
    "/v1/parse",
]


async def _discover_parse_paths(client: httpx.AsyncClient) -> List[str]:
    """
    Try to find parse-like POST endpoints by reading the service's OpenAPI schema.
    """
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
                if "post" in {k.lower() for k in ops.keys()}:
                    post = ops.get("post") or ops.get("POST") or {}
                    op_id = (post.get("operationId") or "").lower()
                    if ("parse" in path.lower()) or ("parse" in op_id):
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
    r = await client.post(url, json=body)
    if r.status_code >= 400:
        # surface server error details to logs
        logger.warning("parser.cobol <- %s status=%s body=%s", url, r.status_code, r.text)
    else:
        logger.info("parser.cobol <- %s status=%s", url, r.status_code)
    r.raise_for_status()
    return r.json()


async def parse_sources(*, sources: List[str], dialect: str = "ANSI85") -> Dict[str, Any]:
    """
    Call the parser service with in-memory COBOL source texts.

    Args:
        sources: List of COBOL program texts (not file paths).
        dialect: One of {"ANSI85", "MF", "OSVS"}.

    Returns:
        Dict parsed from the parser's JSON response (expects a top-level "programs" array).
    """
    body = {"sources": sources, "dialect": dialect}
    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_S) as client:
        # Optional health probe (service may not implement /health; ignore failures)
        try:
            hr = await client.get(f"{BASE}/health")
            logger.info("parser.cobol.health <- %s status=%s", f"{BASE}/health", getattr(hr, "status_code", "?"))
        except Exception:
            pass

        # Build ordered list of candidate paths: discovered first, then defaults (deduped)
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

        last_error: Exception | None = None
        for path in ordered:
            try:
                return await _post_json(client, path, body)
            except httpx.HTTPError as e:
                last_error = e
                continue

    raise (last_error or RuntimeError("parser call failed: no matching endpoint"))


# ───────────────────────── Convenience wrappers expected by tool_runner ─────────────────────────

async def parse_programs(*, program_paths: List[str], dialect: str = "ANSI85") -> Dict[str, Any]:
    """
    Read the given COBOL files and call the parser, returning a normalized {items: [...]}
    structure that tool_runner expects.
    """
    sources: List[str] = []
    safe_paths: List[Path] = []
    for p in program_paths or []:
        pp = Path(p)
        try:
            if pp.is_file():
                # tolerant read: skip undecodable bytes
                sources.append(pp.read_text(encoding="utf-8", errors="ignore"))
                safe_paths.append(pp)
        except Exception as e:
            logger.warning("parser.cobol: failed to read %s: %s", p, e)

    if not sources:
        logger.info("parser.cobol: no program sources to parse (0 files)")
        return {"items": []}

    raw = await parse_sources(sources=sources, dialect=dialect)
    programs = list(raw.get("programs") or [])
    items: List[Dict[str, Any]] = []
    for i, prog in enumerate(programs):
        # Try to name from program payload; otherwise fall back to file name or a synthetic name
        fallback = safe_paths[i].name if i < len(safe_paths) else f"program{i}"
        name = (prog.get("name")
                or prog.get("program")
                or prog.get("id")
                or fallback)
        items.append({"name": str(name), "data": prog})
    return {"items": items}


async def copybook_to_xml(*, copybooks: List[str], encoding: Optional[str] = None) -> Dict[str, Any]:
    """
    Pass-through wrapper for copybook -> XML endpoint; normalize to {items:[...]}.
    """
    body = {"copybooks": copybooks}
    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_S) as client:
        url = f"{BASE}/copybook_to_xml"
        logger.info("parser.cobol -> %s body=%s", url, json.dumps(body, separators=(",", ":")))
        r = await client.post(url, json=body)
        if r.status_code >= 400:
            logger.warning("parser.cobol <- %s status=%s body=%s", url, r.status_code, r.text)
        else:
            logger.info("parser.cobol <- %s status=%s", url, r.status_code)
        r.raise_for_status()
        data = r.json()
    xml_docs = list(data.get("xmlDocs") or [])
    items = [{"name": f"copybook{i}.xml", "data": x} for i, x in enumerate(xml_docs)]
    return {"items": items}


# Optional stubs so tool_runner calls won't explode even if not yet implemented server-side.
# Replace with real endpoints when available.
async def paragraph_flow() -> Dict[str, Any]:
    return {}

async def file_mapping() -> Dict[str, Any]:
    return {}


# ───────────────────────── Drop-in helper: read files from landing zone ─────────────────────────

LANDING = getattr(settings, "LANDING_ZONE", "/landing_zone")


def _is_within(child: Path, parent: Path) -> bool:
    """
    True if `child` is the same as `parent` or located under it (after resolving symlinks).
    """
    try:
        child_r = child.resolve()
        parent_r = parent.resolve()
        return parent_r == child_r or parent_r in child_r.parents
    except Exception:
        return False


def _strip_leading_repo(rel: str) -> str:
    """
    The fetcher manifest may return paths relative to the *workspace root* (e.g. 'repo/src/foo.cbl').
    The parser helper reads from <LANDING>/<workspace>/repo, so we strip a leading 'repo/' if present.
    """
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
    """
    Convenience helper to read COBOL files from the shared landing zone and call the parser.

    Args:
        workspace: The landing_subdir/workspace used during fetch (e.g., run_id).
        rel_paths: Paths relative to the *workspace root* as returned by the fetcher manifest
                   (e.g., 'repo/src/foo.cbl'). Paths already relative to repo are also accepted.
        dialect: COBOL dialect for the parser.

    Returns:
        Dict parsed from the parser's JSON response normalized to {items:[...]}.
    """
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
        raise RuntimeError(
            "No COBOL files found under the workspace for the given rel_paths."
        )

    logger.info(
        "parser_proleap: collected %d file(s) from workspace '%s' (repo root: %s)",
        len(paths),
        workspace,
        repo_root,
    )
    return await parse_programs(program_paths=paths, dialect=dialect)
