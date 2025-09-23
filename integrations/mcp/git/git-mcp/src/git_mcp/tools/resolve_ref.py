# integrations/mcp/git/git-mcp/src/git_mcp/tools/resolve_ref.py
from __future__ import annotations

from typing import Any, Dict

from ..util.fs import ensure_under_root
from ..util.git_cmd import resolve_ref
from ..config import Config


def make_handler(cfg: Config):
    def handler(args: Dict[str, Any]) -> Dict[str, Any]:
        root = args["root"]
        ref = args["ref"]
        root_p = str(ensure_under_root(cfg.work_root, root))
        sha = resolve_ref(root_p, ref)
        return {
            "content": [{"type": "text", "text": sha}],
            "structuredContent": {"commit": sha},
            "isError": False
        }
    return handler


INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["root", "ref"],
    "properties": {
        "root": {"type": "string"},
        "ref": {"type": "string"}
    },
    "additionalProperties": False
}

OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["commit"],
    "properties": {
        "commit": {"type": "string"}
    },
    "additionalProperties": False
}
