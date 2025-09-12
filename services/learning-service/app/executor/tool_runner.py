# services/learning-service/app/executor/tool_runner.py
from __future__ import annotations
from typing import Any, Dict, List, Tuple
from pathlib import Path, PurePosixPath
from glob import glob
import json
import re
import logging

from app.clients import fetcher_github as gh
from app.clients import parser_proleap as proleap
from app.clients import parser_jcl, analyzer_db2
from app.config import settings

log = logging.getLogger("app.executor.tool_runner")

def _lz(*, landing_zone: str, landing_subdir: str, repo_tail: str = "") -> str:
    base = PurePosixPath(landing_zone) / landing_subdir
    return str(base / repo_tail) if repo_tail else str(base)

def _first(*vals):
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        return v
    return None

_GH_SHORT_RE = re.compile(r"^[\w\-.]+/[\w\-.]+(?:\.git)?$")

def _normalize_repo_url(repo: str) -> str:
    repo = (repo or "").strip()
    if not repo:
        return repo
    if repo.startswith("git@"):
        m = re.match(r"^git@([^:]+):(.+)$", repo)
        if m:
            host, path = m.group(1), m.group(2).lstrip("/")
            return f"https://{host}/{path}"
    if "://" not in repo and _GH_SHORT_RE.match(repo):
        return f"https://github.com/{repo.lstrip('/')}"
    return repo

def _extract_repo_inputs(params: Dict[str, Any], runtime: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accept flexible forms...
    """
    repo_param = params.get("repo")
    repo_url_param = params.get("repo_url")
    # If repo is a dict, use its keys
    if isinstance(repo_param, dict):
        repo_url = _first(repo_param.get("repo_url"), repo_param.get("url"), repo_param.get("remote"))
        ref = _first(repo_param.get("ref"), repo_param.get("branch"), params.get("ref"), "main")
        depth = _first(repo_param.get("depth"), params.get("depth"), 1)
        sparse_globs = _first(repo_param.get("sparse_globs"), params.get("sparse_globs")) or []
    else:
        # repo is likely a string
        repo_url = _first(repo_url_param, repo_param)
        ref = _first(params.get("ref"), "main")
        depth = _first(params.get("depth"), 1)
        sparse_globs = list(params.get("sparse_globs") or [])

    # runtime fallbacks (best-effort, very lenient)
    run_repo = ((runtime.get("run") or {}).get("repo")  # type: ignore
                or runtime.get("repo")  # type: ignore
                or {})
    if not repo_url:
        repo_url = _first(run_repo.get("repo_url"), run_repo.get("url"), run_repo.get("remote"))

    repo_url = _normalize_repo_url(str(repo_url or ""))

    return {
        "repo_url": repo_url,
        "ref": str(ref or "main"),
        "depth": int(0 if depth in (0, None) else 1),
        "sparse_globs": list(sparse_globs or []),
    }

def _kinds(items: List[dict]) -> List[str]:
    return sorted({(a or {}).get("kind", "") for a in items if isinstance(a, dict)})

async def run_tool(tool_key: str, params: Dict[str, Any], runtime: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str], Dict[str, Any]]:
    """
    Returns (artifacts, logs, extras). extras may include {"repo_path": "..."} for later steps.
    """
    logs: List[str] = []
    artifacts: List[Dict[str, Any]] = []
    extras: Dict[str, Any] = {}

    con = runtime.get("connectors", {})
    ws = runtime.get("workspace", {})
    landing_zone = (con.get("fetcher.scm.github") or {}).get("landing_zone") or settings.LANDING_ZONE
    landing_subdir = ws.get("landing_subdir") or ws.get("name") or "workspace"

    if tool_key == "tool.github.fetch":
        inp = _extract_repo_inputs(params, runtime)
        body_preview = {
            "repo_url": inp["repo_url"],
            "ref": inp["ref"],
            "depth": inp["depth"],
            "sparse_globs": inp["sparse_globs"],
            "landing_subdir": landing_subdir,  # client maps to workspace for /fetch
        }
        logs.append("clone.body=" + json.dumps(body_preview, separators=(",", ":")))
        log.info("tool_runner.github.fetch", extra={"repo_url": body_preview["repo_url"], "ref": body_preview["ref"]})

        resp = await gh.clone(
            repo_url=body_preview["repo_url"],
            landing_subdir=landing_subdir,
            ref=body_preview["ref"],
            depth=body_preview["depth"],
            sparse_globs=body_preview["sparse_globs"],
        )

        repo_path = resp.get("path") or _lz(landing_zone=landing_zone, landing_subdir=landing_subdir, repo_tail="repo")
        commit_like = resp.get("commit") or resp.get("ref") or ""

        extras["repo_path"] = repo_path
        logs.append(f"clone: {repo_path}@{commit_like}")

        globs_patterns = inp["sparse_globs"] or ["**/*"]
        matched: List[str] = []
        for gpat in globs_patterns:
            matched.extend(glob(str(Path(repo_path) / gpat), recursive=True))
        files = [str(Path(p).relative_to(repo_path)) for p in matched if Path(p).is_file()]

        repo_name = Path(repo_path).name
        artifacts.append({"kind": "cam.source.repository", "name": repo_name, "data": {"path": repo_path, "commit": commit_like}})
        artifacts.append({"kind": "cam.source.manifest", "name": f"{repo_name} manifest", "data": {"count": len(files), "globs": globs_patterns}})
        for f in files:
            artifacts.append({"kind": "cam.source.file", "name": f, "data": {"path": f}})
        logs.append(f"manifest: files={len(files)}")
        logs.append(f"kinds.emitted={_kinds(artifacts)}")
        return artifacts, logs, extras

    if tool_key == "tool.cobol.parse":
        repo_path = (runtime.get("extras") or {}).get("repo_path")
        globs_patterns = list(params.get("globs") or ["**/*.cbl", "**/*.CBL", "**/*.cob", "**/*.COB"])
        program_paths = list(params.get("program_paths") or [])

        if not program_paths:
            if repo_path:
                matched: List[str] = []
                for gpat in globs_patterns:
                    matched.extend(glob(str(Path(repo_path) / gpat), recursive=True))
                program_paths = [str(Path(p)) for p in matched if Path(p).is_file()]
                logs.append(f"cobol.parse: discovered {len(program_paths)} program(s) via globs")
            else:
                logs.append("cobol.parse: no program_paths provided and missing repo_path (ensure tool.github.fetch ran earlier)")

        log.info("tool_runner.cobol.parse.request", extra={"program_paths": len(program_paths)})
        resp = await proleap.parse_programs(
            program_paths=program_paths,
            dialect=str(params.get("dialect") or "ANSI85"),
        )
        items = resp.get("items") or []
        for it in items:
            artifacts.append({"kind": "cam.cobol.program", "name": it.get("name") or "COBOL Program", "data": it.get("data")})
        logs.append(f"cobol.parse: programs={len(items)}")
        logs.append(f"kinds.emitted={_kinds(artifacts)}")
        return artifacts, logs, extras

    if tool_key == "tool.copybook.to_xml":
        log.info("tool_runner.copybook.to_xml.request", extra={"count": len(list(params.get("copybooks") or []))})
        resp = await proleap.copybook_to_xml(copybooks=list(params.get("copybooks") or []), encoding=params.get("encoding"))
        for it in (resp.get("items") or []):
            artifacts.append({"kind": "cam.cobol.copybook", "name": it.get("name") or "Copybook", "data": it.get("data")})
        logs.append(f"copybook.to_xml: items={len(artifacts)}")
        logs.append(f"kinds.emitted={_kinds(artifacts)}")
        return artifacts, logs, extras

    if tool_key == "tool.cobol.flow":
        resp = await proleap.paragraph_flow()
        if resp:
            artifacts.append({"kind": "cam.cobol.paragraph_flow", "name": "Paragraph Flow", "data": resp})
        logs.append("cobol.flow: done")
        logs.append(f"kinds.emitted={_kinds(artifacts)}")
        return artifacts, logs, extras

    if tool_key == "tool.cobol.filemap":
        resp = await proleap.file_mapping()
        if resp:
            artifacts.append({"kind": "cam.cobol.file_mapping", "name": "File I/O Mapping", "data": resp})
        logs.append("cobol.filemap: done")
        logs.append(f"kinds.emitted={_kinds(artifacts)}")
        return artifacts, logs, extras

    if tool_key == "tool.jcl.parse":
        repo_path = (runtime.get("extras") or {}).get("repo_path")
        globs_patterns = list(params.get("globs") or ["**/*.jcl", "**/*.JCL", "**/*.proc", "**/*.PROC"])
        if not repo_path:
            logs.append("jcl.parse: missing repo_path (ensure tool.github.fetch ran earlier)")
            return artifacts, logs, extras

        matched: List[str] = []
        for gpat in globs_patterns:
            matched.extend(glob(str(Path(repo_path) / gpat), recursive=True))
        jcl_paths = [str(Path(p)) for p in matched if Path(p).is_file()]

        log.info("tool_runner.jcl.parse.request", extra={"jcl_paths": len(jcl_paths)})
        resp = await parser_jcl.parse(paths=jcl_paths)
        jobs = resp.get("jobs") or []
        steps = resp.get("steps") or []

        for j in jobs:
            name = j.get("name") or j.get("id") or "JCL Job"
            artifacts.append({"kind": "cam.jcl.job", "name": name, "data": j})
        for s in steps:
            name = s.get("name") or f"{s.get('job', 'job')}:{s.get('id', 'step')}"
            artifacts.append({"kind": "cam.jcl.step", "name": name, "data": s})

        logs.append(f"jcl.parse: jobs={len(jobs)} steps={len(steps)}")
        logs.append(f"kinds.emitted={_kinds(artifacts)}")
        return artifacts, logs, extras

    if tool_key == "tool.db2.usage":
        repo_path = (runtime.get("extras") or {}).get("repo_path")
        globs_patterns = list(params.get("globs") or ["**/*.cbl", "**/*.CBL", "**/*.cob", "**/*.COB"])
        if not repo_path:
            logs.append("db2.usage: missing repo_path (ensure tool.github.fetch ran earlier)")
            return artifacts, logs, extras

        matched: List[str] = []
        for gpat in globs_patterns:
            matched.extend(glob(str(Path(repo_path) / gpat), recursive=True))
        prog_paths = [str(Path(p)) for p in matched if Path(p).is_file()]

        log.info("tool_runner.db2.usage.request", extra={"program_paths": len(prog_paths)})
        resp = await analyzer_db2.usage(program_paths=prog_paths)
        items = resp.get("items") or []
        for it in items:
            pname = it.get("program") or "DB2 Usage"
            artifacts.append({"kind": "cam.db2.table_usage", "name": pname, "data": it})

        logs.append(f"db2.usage: items={len(items)}")
        logs.append(f"kinds.emitted={_kinds(artifacts)}")
        return artifacts, logs, extras

    logs.append(f"skip: unsupported tool '{tool_key}'")
    log.info("tool_runner.skip", extra={"tool": tool_key})
    return artifacts, logs, extras
