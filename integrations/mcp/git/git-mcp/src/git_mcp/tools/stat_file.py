from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..util.fs import ensure_under_root, sha256_of_file
from ..config import Config


def make_handler(cfg: Config):
    def handler(args: Dict[str, Any]) -> Dict[str, Any]:
        root = args["root"]
        path = args["path"]
        root_p = ensure_under_root(cfg.work_root, root)
        file_p = ensure_under_root(str(root_p), str(Path(root_p) / path))
        exists = file_p.exists()
        meta = {"exists": exists}
        if exists and file_p.is_file():
            meta.update({
                "size_bytes": file_p.stat().st_size,
                "sha256": sha256_of_file(file_p),
                "last_modified": int(file_p.stat().st_mtime)
            })
        return {
            "content": [{"type": "text", "text": "ok"}],
            "structuredContent": meta,
            "isError": False
        }
    return handler


INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["root", "path"],
    "properties": {
        "root": {"type": "string"},
        "path": {"type": "string"}
    },
    "additionalProperties": False
}

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["exists"],
    "properties": {
        "exists": {"type": "boolean"},
        "size_bytes": {"type": "integer"},
        "sha256": {"type": "string"},
        "last_modified": {"type": "integer"}
    },
    "additionalProperties": False
}
