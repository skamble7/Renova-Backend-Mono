# integrations/mcp/git/git-mcp/src/git_mcp/tools/ls_tree.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from ..util.fs import ensure_under_root, list_files, sha256_of_file
from ..config import Config


def make_handler(cfg: Config):
    def handler(args: Dict[str, Any]) -> Dict[str, Any]:
        root = args["root"]
        globs: List[str] = args.get("globs", [])
        root_p = ensure_under_root(cfg.work_root, root)
        files = []
        for p in list_files(str(root_p), globs):
            rel = str(p.relative_to(root_p))
            files.append({
                "relpath": rel,
                "size_bytes": p.stat().st_size,
                "sha256": sha256_of_file(p)
            })
        return {
            "content": [{"type": "text", "text": f"Found {len(files)} files"}],
            "structuredContent": {"files": files},
            "isError": False
        }
    return handler


INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["root"],
    "properties": {
        "root": {"type": "string"},
        "globs": {"type": "array", "items": {"type": "string"}}
    },
    "additionalProperties": False
}

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["files"],
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["relpath", "size_bytes", "sha256"],
                "properties": {
                    "relpath": {"type": "string"},
                    "size_bytes": {"type": "integer"},
                    "sha256": {"type": "string"}
                },
                "additionalProperties": False
            }
        }
    },
    "additionalProperties": False
}
