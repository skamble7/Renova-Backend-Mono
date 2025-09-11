from __future__ import annotations
import json
import logging
import re
from typing import Dict, Any, List, Optional

import httpx
from app.config import settings

logger = logging.getLogger("app.clients.fetcher_github")

BASE = settings.GITHUB_FETCHER_BASE_URL.rstrip("/")

# A broad set of likely clone endpoints. We’ll also auto-discover via OpenAPI.
DEFAULT_CLONE_PATHS: List[str] = [
    "/v1/clone",
    "/clone",
    "/v1/github/clone",
    "/api/v1/clone",
    "/github/clone",
    "/v1/fetch",
    "/v1/repo/clone",
    "/repo/clone",
    "/v1/scm/clone",
    "/api/v1/github/clone",
    "/api/v1/github/fetch",
    "/v1/git/clone",
    "/git/clone",
    "/repos/clone",
    "/v1/repos/clone",
    "/api/repos/clone",
    "/api/v1/repos/clone",
    # Your fetcher’s actual route:
    "/fetch",
]

def _candidate_clone_paths_from_env() -> List[str]:
    val = (getattr(settings, "GITHUB_FETCHER_CLONE_PATHS", None) or "").strip()
    if not val:
        return []
    raw = [p.strip() for p in val.replace(",", " ").split() if p.strip()]
    return [p if p.startswith("/") else f"/{p}" for p in raw]

async def _discover_clone_paths(client: httpx.AsyncClient) -> List[str]:
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
                    if ("clone" in path.lower()) or ("clone" in op_id) or ("fetch" in path.lower()) or ("fetch" in op_id):
                        discovered.append(path)
            discovered = [p if p.startswith("/") else f"/{p}" for p in discovered]
            if discovered:
                logger.info("github.fetch.clone: discovered via openapi %s", discovered)
                return discovered
        except Exception:
            continue
    return []

_GH_SHORT_RE = re.compile(r"^[\w\-.]+/[\w\-.]+(?:\.git)?$")

def _normalize_repo_url(repo_url: str) -> str:
    """
    Convert common short/SSH forms into a valid https URL so FastAPI's HttpUrl accepts it.
    """
    repo_url = (repo_url or "").strip()
    if not repo_url:
        return repo_url

    # git@github.com:org/repo(.git)
    if repo_url.startswith("git@"):
        # git@host:org/repo(.git) -> https://host/org/repo(.git)
        m = re.match(r"^git@([^:]+):(.+)$", repo_url)
        if m:
            host, path = m.group(1), m.group(2).lstrip("/")
            return f"https://{host}/{path}"

    # Short GitHub form org/repo(.git)
    if "://" not in repo_url and _GH_SHORT_RE.match(repo_url):
        return f"https://github.com/{repo_url.lstrip('/')}"

    return repo_url

def _make_body_for_path(path: str, *, repo_url: str, ref: str, landing_subdir: str,
                        depth: int, sparse_globs: Optional[List[str]]) -> Dict[str, Any]:
    p = path.lower()
    if p == "/fetch" or ("/fetch" in p and "clone" not in p):
        # Your FastAPI service model: FetchRequest(repo_url, ref, workspace)
        return {
            "repo_url": _normalize_repo_url(repo_url),
            "ref": ref or "main",
            "workspace": landing_subdir,
        }
    # Generic clone-style
    return {
        "repo_url": _normalize_repo_url(repo_url),
        "ref": ref or "main",
        "depth": 1 if depth not in (0, None) else 0,
        "sparse_globs": sparse_globs or [],
        "landing_subdir": landing_subdir,
    }

async def clone(
    *,
    repo_url: str,
    landing_subdir: str,
    ref: str = "main",
    depth: int = 1,
    sparse_globs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    body_template = {
        "repo_url": repo_url,
        "ref": ref or "main",
        "depth": 1 if depth not in (0, None) else 0,
        "sparse_globs": sparse_globs or [],
        "landing_subdir": landing_subdir,
    }

    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_S) as client:
        try:
            hr = await client.get(f"{BASE}/health")
            logger.info("github.fetch.health <- %s status=%s", f"{BASE}/health", getattr(hr, "status_code", "?"))
        except Exception:
            pass

        candidates: List[str] = []
        candidates += _candidate_clone_paths_from_env()
        try:
            candidates += await _discover_clone_paths(client)
        except Exception:
            pass

        seen = set()
        ordered = [p for p in candidates if not (p in seen or seen.add(p))]
        for p in DEFAULT_CLONE_PATHS:
            if p not in seen:
                ordered.append(p); seen.add(p)

        last_error: Exception | None = None
        for path in ordered:
            url = f"{BASE}{path}"
            body = _make_body_for_path(
                path,
                repo_url=repo_url,
                ref=ref,
                landing_subdir=landing_subdir,
                depth=depth,
                sparse_globs=sparse_globs,
            )
            try:
                logger.info("github.fetch.clone -> %s body=%s", url, json.dumps(body, separators=(",", ":")))
                r = await client.post(url, json=body)
                # Log body on error to surface FastAPI's detail
                if r.status_code >= 400:
                    try:
                        logger.warning("github.fetch.clone <- %s status=%s body=%s", url, r.status_code, r.text)
                    except Exception:
                        logger.warning("github.fetch.clone <- %s status=%s (no body)", url, r.status_code)
                else:
                    logger.info("github.fetch.clone <- %s status=%s", url, r.status_code)

                r.raise_for_status()
                return r.json()
            except httpx.HTTPError as e:
                last_error = e
                continue

    logger.error("github.fetch.clone FAILED all endpoints; last_error=%r", last_error)
    raise (last_error or RuntimeError("fetcher clone failed: no matching endpoint"))

async def checkout(*, repo_path: str, ref: str, sparse_globs: Optional[List[str]] = None) -> Dict[str, Any]:
    body = {"repo_path": repo_path, "ref": ref, "sparse_globs": sparse_globs or []}
    url = f"{BASE}/v1/checkout"
    logger.info("github.fetch.checkout -> %s body=%s", url, json.dumps(body, separators=(",", ":")))
    async with httpx.AsyncClient(timeout=settings.REQUEST_TIMEOUT_S) as client:
        r = await client.post(url, json=body)
        logger.info("github.fetch.checkout <- %s status=%s", url, r.status_code)
        r.raise_for_status()
        return r.json()
