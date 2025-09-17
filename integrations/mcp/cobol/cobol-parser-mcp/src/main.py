# integrations/mcp/cobol/cobol-parser-mcp/src/main.py
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
import time
from typing import Any, Dict, List, Tuple

from src.utils.discovery import walk_sources, filter_paths
from src.utils.encoding import detect_encoding
from src.utils.hashing import sha256_bytes
from src.utils.validator import SchemaRegistry
from src.parser.proleap_adapter import ProLeapAdapter
from src.parser.normalizer import normalize_copybook, normalize_program

_shutdown = False


# ----------------------------- Signals ---------------------------------
def _sigterm_handler(signum, frame):
    global _shutdown
    _shutdown = True


signal.signal(signal.SIGTERM, _sigterm_handler)
signal.signal(signal.SIGINT, _sigterm_handler)


# --------------------------- Path Normalizer ---------------------------
def _normalize_root(root: str) -> str:
    """
    Map a host path to the container mount so the tool works across
    local dev, UAT, and prod.

    Env vars:
      WORKSPACE_HOST: absolute host path (e.g. /Users/alice/Projects/Renova)
      WORKSPACE_CONTAINER: mount path inside container (default: /mnt/work)
    """
    if not root:
        return root

    ws_host = os.environ.get("WORKSPACE_HOST")
    ws_ctr = os.environ.get("WORKSPACE_CONTAINER", "/mnt/work")

    # Already container-relative?
    if root.startswith(ws_ctr):
        return root

    # Normalize Windows-style paths C:\foo\bar → /c/foo/bar
    r = root
    if re.match(r"^[A-Za-z]:\\", r):
        drive, rest = r[:2], r[2:]
        r = f"/{drive[0].lower()}{rest}".replace("\\", "/")
    else:
        r = r.replace("\\", "/")

    # Replace workspace host prefix with container prefix
    if ws_host:
        ws_host_norm = ws_host.replace("\\", "/").rstrip("/")
        if r.startswith(ws_host_norm + "/") or r == ws_host_norm:
            suffix = r[len(ws_host_norm):].lstrip("/")
            return os.path.join(ws_ctr, suffix) if suffix else ws_ctr

    # Relative paths → resolve against container workspace
    if not r.startswith("/"):
        return os.path.normpath(os.path.join(ws_ctr, r))

    # As-is if valid, else best-effort remap
    if os.path.exists(r):
        return r
    return os.path.join(ws_ctr, r.lstrip("/"))


# ------------------------------ Tools ----------------------------------
def list_tools() -> Dict[str, Any]:
    return {
        "tools": [
            {
                "name": "parse_tree",
                "description": "Parse COBOL programs and copybooks; normalize to CAM kinds.",
                "inputSchema": {
                    "type": "object",
                    "required": ["root"],
                    "properties": {
                        "root": {"type": "string"},
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "dialect": {
                            "type": "string",
                            "enum": ["COBOL85", "ENTERPRISE", "IBM"],
                            "default": "COBOL85",
                        },
                        "use_source_index": {"type": "boolean", "default": True},
                    },
                    "additionalProperties": False,
                },
            }
        ]
    }


def parse_tree(inp: Dict[str, Any]) -> Dict[str, Any]:
    root = inp.get("root")
    if not root or not isinstance(root, str):
        raise ValueError("`root` must be a non-empty string")

    root = _normalize_root(root)
    dialect = inp.get("dialect", "COBOL85")
    allow_paths = inp.get("paths") or []

    diagnostics: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []
    stats = {
        "files_scanned": 0,
        "programs_emitted": 0,
        "copybooks_emitted": 0,
        "parser_version": "normalizer=1.0.0,adapter=proleap/0.0.1",
    }

    if not os.path.isdir(root):
        diagnostics.append(
            {"level": "error", "relpath": "", "message": f"Root not a directory: {root}"}
        )
        return {"artifacts": [], "diagnostics": diagnostics, "stats": stats}

    schema_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "schemas"))
    registry = SchemaRegistry(schema_dir)
    adapter = ProLeapAdapter()

    items = walk_sources(root)
    items = list(filter_paths(items, allow_paths))

    for abs_p, rel_p, kind in items:
        stats["files_scanned"] += 1
        try:
            with open(abs_p, "rb") as f:
                raw = f.read()
        except Exception as e:
            diagnostics.append(
                {"level": "warning", "relpath": rel_p, "message": f"Read error: {e}"}
            )
            continue

        enc, payload = detect_encoding(raw)
        try:
            text = payload.decode(enc, errors="strict")
        except Exception as e:
            diagnostics.append(
                {"level": "warning", "relpath": rel_p, "message": f"Decode failed ({enc}): {e}"}
            )
            continue

        content_hash = sha256_bytes(payload)

        if kind == "cobol":
            ast = adapter.parse_program(text=text, relpath=rel_p, dialect=dialect)
            data = normalize_program(ast, relpath=rel_p, sha256=content_hash)
            artifact = {"kind": "cam.cobol.program", "version": "1.0.0", "data": data}
            errors = registry.validate(artifact)
            if errors:
                diagnostics.append(
                    {
                        "level": "warning",
                        "relpath": rel_p,
                        "message": f"Schema: {errors[:3]}{'...' if len(errors)>3 else ''}",
                    }
                )
            else:
                stats["programs_emitted"] += 1
                artifacts.append(artifact)

        elif kind == "copybook":
            ast = adapter.parse_copybook(text=text, relpath=rel_p, dialect=dialect)
            data = normalize_copybook(ast, relpath=rel_p, sha256=content_hash)
            artifact = {"kind": "cam.cobol.copybook", "version": "1.0.0", "data": data}
            errors = registry.validate(artifact)
            if errors:
                diagnostics.append(
                    {
                        "level": "warning",
                        "relpath": rel_p,
                        "message": f"Schema: {errors[:3]}{'...' if len(errors)>3 else ''}",
                    }
                )
            else:
                stats["copybooks_emitted"] += 1
                artifacts.append(artifact)

    def _sort_key(a: Dict[str, Any]) -> Tuple[str, str, str]:
        data = a.get("data", {})
        rel = (data.get("source") or {}).get("relpath", "")
        name = data.get("program_id") or data.get("name") or ""
        return (a.get("kind", ""), rel, name)

    artifacts.sort(key=_sort_key)
    return {"artifacts": artifacts, "diagnostics": diagnostics, "stats": stats}


# ------------------------------ Protocol --------------------------------
def _send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _send_error(
    id_val: Any, code: int, message: str, data: Dict[str, Any] | None = None
) -> None:
    _send(
        {
            "jsonrpc": "2.0",
            "id": id_val,
            "error": {"code": code, "message": message, "data": data or {}},
        }
    )


def _handle_initialize(msg: Dict[str, Any]) -> None:
    result = {
        "protocolVersion": "0.1",
        "serverInfo": {"name": "mcp.cobol.parser", "version": "0.0.1"},
        "capabilities": {"tools": {}},
    }
    _send({"jsonrpc": "2.0", "id": msg.get("id"), "result": result})


def _handle_initialized(_msg: Dict[str, Any]) -> None:
    return


def _handle_shutdown(msg: Dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": msg.get("id"), "result": None})


def _handle_tools_list(msg: Dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": msg.get("id"), "result": list_tools()})


def _handle_tools_call(msg: Dict[str, Any]) -> None:
    params = msg.get("params") or {}
    name = params.get("name")
    arguments = params.get("arguments") or {}

    if name != "parse_tree":
        _send_error(msg.get("id"), -32601, f"Unknown tool: {name}")
        return

    try:
        res = parse_tree(arguments)
        st = res.get("stats", {})
        diags = res.get("diagnostics", [])
        summary = (
            f"COBOL parse complete. Scanned={st.get('files_scanned', 0)}, "
            f"programs={st.get('programs_emitted', 0)}, "
            f"copybooks={st.get('copybooks_emitted', 0)}, "
            f"diagnostics={len(diags)}."
        )
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "result": {
                    "content": [{"type": "text", "text": summary}],
                    "structuredContent": res,
                },
            }
        )
    except Exception as e:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "result": {"content": [{"type": "text", "text": str(e)}], "isError": True},
            }
        )


def run_stdio_loop() -> None:
    print("mcp server ready", file=sys.stderr, flush=True)
    for line in sys.stdin:
        if not line:
            time.sleep(0.01)
            continue
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method")
        if method == "initialize":
            _handle_initialize(msg)
        elif method == "notifications/initialized":
            _handle_initialized(msg)
        elif method == "shutdown":
            _handle_shutdown(msg)
        elif method == "tools/list":
            _handle_tools_list(msg)
        elif method == "tools/call":
            _handle_tools_call(msg)
        elif method == "exit":
            break
        else:
            _send_error(msg.get("id"), -32601, f"Unknown method: {method}")


# -------------------------------- Main ---------------------------------
def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser("cobol-parser-mcp")
    ap.add_argument("--stdio", action="store_true")
    _ = ap.parse_args(argv)
    run_stdio_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
