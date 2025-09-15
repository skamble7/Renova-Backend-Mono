from __future__ import annotations

import json
from typing import Any, Dict

from ..config import Config
from ..util.git_cmd import clone_or_update


def make_handler(cfg: Config):
    def handler(args: Dict[str, Any]) -> Dict[str, Any]:
        url: str = args["url"]
        branch: str = args.get("branch", "main")
        depth: int = int(args.get("depth", 0))
        dest: str = args.get("dest", f"{cfg.work_root}/repo")

        sha, dest_path = clone_or_update(
            url, branch, dest, depth,
            cfg.work_root, cfg.cache_root,
            use_reference=not cfg.disable_reference
        )

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
        return {
            "content": [{"type": "text", "text": json.dumps({"artifacts": [artifact]})}],
            "structuredContent": {"artifacts": [artifact]},
            "isError": False
        }
    return handler


# Keep the schema at module scope so imports like t_clone.INPUT_SCHEMA work reliably
INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["url"],
    "properties": {
        "url": {"type": "string"},
        "branch": {"type": "string", "default": "main"},
        "depth": {"type": "integer", "minimum": 0, "default": 0},
        "dest": {"type": "string"}
    },
    "additionalProperties": False
}
