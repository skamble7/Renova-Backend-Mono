from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from ..util.fs import ensure_under_root
from ..config import Config


def make_handler(cfg: Config):
    def handler(args: Dict[str, Any]) -> Dict[str, Any]:
        root = args["root"]
        path = args["path"]
        max_bytes = int(args.get("max_bytes", 1024 * 1024))
        encoding = args.get("encoding", "utf-8")

        root_p = ensure_under_root(cfg.work_root, root)
        file_p = ensure_under_root(str(root_p), str(Path(root_p) / path))
        data = file_p.read_bytes()[:max_bytes]
        text = data.decode(encoding, errors="replace")

        return {
            "content": [{"type": "text", "text": text}],
            "structuredContent": {
                "path": str(file_p.relative_to(root_p)),
                "size_bytes": file_p.stat().st_size,
            },
            "isError": False
        }
    return handler


INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["root", "path"],
    "properties": {
        "root": {"type": "string"},
        "path": {"type": "string"},
        "max_bytes": {"type": "integer", "minimum": 1, "default": 1048576},
        "encoding": {"type": "string", "default": "utf-8"}
    },
    "additionalProperties": False
}
