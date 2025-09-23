from __future__ import annotations

import json
import sys
from urllib.parse import urlparse
from typing import Any, Dict

from ..config import Config
from ..util.git_cmd import clone_or_update


def _safe_repo_dir(url: str) -> str:
    """
    Stable, human-ish folder name under work_root: <owner>-<repo>
    e.g., github.com/aws-samples/aws-mainframe-modernization-carddemo
      -> aws-samples-aws-mainframe-modernization-carddemo
    """
    p = urlparse(url)
    parts = [seg for seg in p.path.split("/") if seg]
    if parts:
        repo = parts[-1]
        if repo.endswith(".git"):
            repo = repo[:-4]
        owner = parts[-2] if len(parts) >= 2 else (p.hostname or "repo")
        return f"{owner}-{repo}"
    return "repo"


def make_handler(cfg: Config):
    def handler(args: Dict[str, Any]) -> Dict[str, Any]:
        url: str = args["url"]
        branch: str = args.get("branch", "main")
        depth: int = int(args.get("depth", 0))

        # Treat absolute dests as relative folders under work_root
        dest_arg = args.get("dest")
        dest_rel = dest_arg.lstrip("/") if isinstance(dest_arg, str) and dest_arg else _safe_repo_dir(url)

        # stderr logging is safe; stdout is reserved for MCP JSON
        print(f"[git-mcp] clone_repo url={url} branch={branch} dest_rel={dest_rel}", file=sys.stderr, flush=True)

        sha, dest_path = clone_or_update(
            url, branch, dest_rel, depth,
            cfg.work_root, cfg.cache_root,
            use_reference=not cfg.disable_reference
        )

        # IMPORTANT: Match the strict output schema:
        # artifacts: [{ kind, version: "1.0.0", body: { repo, commit, branch, paths_root, tags[] } }]
        artifact = {
            "kind": "cam.asset.repo_snapshot",
            "version": "1.0.0",
            "body": {
                "repo": url,
                "commit": sha,
                "branch": branch,
                "paths_root": dest_path,
                "tags": []
            }
        }

        payload = {"artifacts": [artifact]}

        return {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "structuredContent": payload,
            "isError": False
        }
    return handler


INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["url"],
    "properties": {
        "url": {"type": "string"},
        "branch": {"type": "string", "default": "main"},
        "depth": {"type": "integer", "minimum": 0, "default": 0},
        "dest": {"type": "string"}  # relative to REPO_WORK_ROOT; absolute will be treated as relative
    },
    "additionalProperties": False
}
