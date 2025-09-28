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
from src.utils.indexer import build_source_index, derive_copy_paths
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
    if not root:
        return root

    ws_host = os.environ.get("WORKSPACE_HOST")
    ws_ctr = os.environ.get("WORKSPACE_CONTAINER", "/mnt/work")

    if root.startswith(ws_ctr):
        return root

    r = root
    if re.match(r"^[A-Za-z]:\\", r):
        drive, rest = r[:2], r[2:]
        r = f"/{drive[0].lower()}{rest}".replace("\\", "/")
    else:
        r = r.replace("\\", "/")

    if ws_host:
        ws_host_norm = ws_host.replace("\\", "/").rstrip("/")
        if r.startswith(ws_host_norm + "/") or r == ws_host_norm:
            suffix = r[len(ws_host_norm):].lstrip("/")
            return os.path.join(ws_ctr, suffix) if suffix else ws_ctr

    if not r.startswith("/"):
        return os.path.normpath(os.path.join(ws_ctr, r))

    if os.path.exists(r):
        return r
    return os.path.join(ws_ctr, r.lstrip("/"))

# ------------------------------ Tools ----------------------------------
def list_tools() -> Dict[str, Any]:
    return {
        "tools": [
            {
                "name": "parse_tree",
                "description": "Parse COBOL programs and copybooks; normalize to CAM kinds. Also emits cam.asset.source_index. Supports pagination via continuation.",
                "inputSchema": {
                    "type": "object",
                    "required": ["root"],
                    "properties": {
                        "root": {"type": "string"},
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "dialect": {
                            "type": "string",
                            "enum": ["COBOL85", "ENTERPRISE", "IBM"],
                            "default": "COBOL85"
                        },
                        "use_source_index": {"type": "boolean", "default": True},
                        "debug_raw": {
                            "type": "boolean",
                            "description": "If true, dump raw ProLeap/cb2xml XML ASTs to disk.",
                            "default": False
                        },
                        "raw_dump_dir": {
                            "type": "string",
                            "description": "Directory root for raw AST dumps. Defaults to /tmp/proleap_raw (or RAW_AST_DUMP_DIR env)."
                        },
                        "start_at": {
                            "type": "integer",
                            "minimum": 0,
                            "default": 0,
                            "description": "Offset into the target file list (for continuation)."
                        },
                        "file_limit": {
                            "type": "integer",
                            "minimum": 0,
                            "default": 0,
                            "description": "Max files to parse this call (0 = unlimited)."
                        },
                        "budget_seconds": {
                            "type": "number",
                            "minimum": 0,
                            "default": 0,
                            "description": "Soft time budget; when >0 the tool returns partial results and a continuation cursor once reached (0 disables)."
                        }
                    },
                    "additionalProperties": False
                }
            }
        ]
    }

# ------------------------------ Core -----------------------------------
def parse_tree(inp: Dict[str, Any]) -> Dict[str, Any]:
    root = inp.get("root")
    if not root or not isinstance(root, str):
        raise ValueError("`root` must be a non-empty string")

    root = _normalize_root(root)
    dialect = inp.get("dialect", "COBOL85")
    allow_paths = inp.get("paths") or []
    use_source_index: bool = bool(inp.get("use_source_index", True))
    debug_raw: bool = bool(inp.get("debug_raw", False))
    raw_dump_dir: str = inp.get("raw_dump_dir") or os.environ.get("RAW_AST_DUMP_DIR") or "/tmp/proleap_raw"

    # Pagination controls
    start_at: int = int(inp.get("start_at") or 0)
    file_limit: int = int(inp.get("file_limit") or 0)

    # Budget: argument wins; else env; else default 0 (disabled)
    if "budget_seconds" in inp and inp.get("budget_seconds") is not None:
        budget_seconds = float(inp.get("budget_seconds"))
    else:
        env_b = os.environ.get("COBOL_PARSER_BUDGET_SECONDS")
        try:
            budget_seconds = float(env_b) if env_b is not None else 0.0
        except Exception:
            budget_seconds = 0.0

    # If debug_raw is false, ensure env doesn’t force dumps
    if not debug_raw and os.environ.get("RAW_AST_DUMP_DIR"):
        try:
            os.environ.pop("RAW_AST_DUMP_DIR", None)
        except Exception:
            pass

    diagnostics: List[Dict[str, Any]] = []
    artifacts: List[Dict[str, Any]] = []
    stats = {
        "files_scanned": 0,
        "files_total": 0,
        "start_at": max(0, start_at),
        "programs_emitted": 0,
        "copybooks_emitted": 0,
        "parser_version": "normalizer=1.0.0,adapter=proleap/0.0.3",
        "raw_dump_dir": raw_dump_dir if debug_raw else ""
    }

    if not os.path.isdir(root):
        diagnostics.append({"level": "error", "relpath": "", "message": f"Root not a directory: {root}"})
        return {
            "artifacts": [],
            "diagnostics": diagnostics,
            "stats": stats,
            "continuation": {"has_more": False, "next": start_at, "remaining": 0, "total": 0},
        }

    schema_dir = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "schemas"))
    registry = SchemaRegistry(schema_dir)
    adapter = ProLeapAdapter()

    # --- A) Build Source Index ---
    index_data = build_source_index(root)

    # IMPORTANT: derive copy paths BEFORE sanitizing (we need dir hints)
    copy_dirs_rel = derive_copy_paths(index_data)
    copy_dirs_abs = [os.path.join(root, d) for d in copy_dirs_rel]

    # --- Emit cam.asset.source_index (sanitized to match schema) ---
    allowed = {"relpath", "size_bytes", "sha256", "kind", "language_hint", "encoding", "program_id_guess"}
    for f in index_data.get("files", []) or []:
        for k in list(f.keys()):
            if k not in allowed:
                f.pop(k, None)

    idx_artifact = {"kind": "cam.asset.source_index", "version": "1.0.0", "body": index_data}
    if not registry.validate(idx_artifact):
        artifacts.append(idx_artifact)

    # --- B) Choose parse targets ---
    if use_source_index:
        files = index_data.get("files", [])
        if allow_paths:
            allow_set = {p.strip().lstrip("./") for p in allow_paths if p.strip()}
            files = [f for f in files if f.get("relpath") in allow_set]
        files = [f for f in files if f.get("kind") in {"cobol", "copybook"}]
        files.sort(key=lambda f: (f.get("kind") or "", f.get("relpath") or ""))
        targets_all: List[Tuple[str, str, str]] = [
            (os.path.join(root, f["relpath"]), f["relpath"], f["kind"]) for f in files
        ]
        # Fallback: if no copybooks found by index, augment with a direct walk
        if not any(t[2] == "copybook" for t in targets_all):
            extra = list(filter_paths(walk_sources(root), allow_paths))
            extra = [t for t in extra if t[2] == "copybook"]
            if extra:
                targets_all.extend(extra)
    else:
        targets_all = list(filter_paths(walk_sources(root), allow_paths))

    total = len(targets_all)
    stats["files_total"] = total

    if start_at >= total:
        return {
            "artifacts": artifacts,
            "diagnostics": diagnostics,
            "stats": stats,
            "continuation": {"has_more": False, "next": start_at, "remaining": 0, "total": total},
        }

    t0 = time.monotonic()
    processed = 0
    emitted_programs = 0
    emitted_copybooks = 0

    remaining_slice = targets_all[start_at:]
    if file_limit > 0:
        remaining_slice = remaining_slice[:file_limit]

    for abs_p, rel_p, kind in remaining_slice:
        if _shutdown or (budget_seconds and (time.monotonic() - t0) >= budget_seconds):
            break

        stats["files_scanned"] += 1
        processed += 1

        try:
            with open(abs_p, "rb") as f:
                raw = f.read()
        except Exception as e:
            diagnostics.append({"level": "warning", "relpath": rel_p, "message": f"Read error: {e}"})
            continue

        enc, payload = detect_encoding(raw)
        try:
            text = payload.decode(enc, errors="strict")
        except Exception as e:
            diagnostics.append({"level": "warning", "relpath": rel_p, "message": f"Decode failed ({enc}): {e}"})
            continue

        content_hash = sha256_bytes(payload)

        if kind == "cobol":
            ast = adapter.parse_program(text, rel_p, dialect, debug_raw, raw_dump_dir, copy_dirs_abs)
            data = normalize_program(ast, relpath=rel_p, sha256=content_hash)
            artifact = {"kind": "cam.cobol.program", "version": "1.0.0", "body": data}
            errors = registry.validate(artifact)
            if not errors:
                emitted_programs += 1
                artifacts.append(artifact)
            else:
                # make the culprit obvious
                diagnostics.append({
                    "level": "error",
                    "relpath": rel_p,
                    "message": f"cam.cobol.program schema validation failed: {errors[:5]}",
                })

        elif kind == "copybook":
            ast = adapter.parse_copybook(text, rel_p, dialect, debug_raw, raw_dump_dir)
            data = normalize_copybook(ast, relpath=rel_p, sha256=content_hash)
            artifact = {"kind": "cam.cobol.copybook", "version": "1.0.0", "body": data}
            errors = registry.validate(artifact)
            if not errors:
                emitted_copybooks += 1
                artifacts.append(artifact)
            else:
                diagnostics.append({
                    "level": "error",
                    "relpath": rel_p,
                    "message": f"cam.cobol.copybook schema validation failed: {errors[:5]}",
                })

    stats["programs_emitted"] = emitted_programs
    stats["copybooks_emitted"] = emitted_copybooks

    next_offset = start_at + processed
    continuation = {
        "has_more": next_offset < total,
        "next": next_offset,
        "remaining": max(0, total - next_offset),
        "total": total,
    }

    def _sort_key(a: Dict[str, Any]) -> Tuple[str, str, str]:
        body = a.get("body", {}) or {}
        rel = (body.get("source") or {}).get("relpath", "")
        name = body.get("program_id") or body.get("name") or ""
        return (a.get("kind", ""), rel, name)

    artifacts.sort(key=_sort_key)

    return {
        "artifacts": artifacts,
        "diagnostics": diagnostics,
        "stats": stats,
        "continuation": continuation,
    }

# ------------------------------ Protocol --------------------------------
def _send(obj: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()

def _send_error(id_val: Any, code: int, message: str, data: Dict[str, Any] | None = None) -> None:
    _send({"jsonrpc": "2.0", "id": id_val, "error": {"code": code, "message": message, "data": data or {}}})

def _handle_initialize(msg: Dict[str, Any]) -> None:
    result = {
        "protocolVersion": "0.1",
        "serverInfo": {"name": "mcp.cobol.parser", "version": "0.0.3"},
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
        cont = res.get("continuation", {})
        diags = res.get("diagnostics") or []
        summary = (
            f"COBOL parse {'partial' if cont.get('has_more') else 'complete'}."
            f" scanned={st.get('files_scanned', 0)} start_at={st.get('start_at', 0)}"
            f" programs={st.get('programs_emitted', 0)} copybooks={st.get('copybooks_emitted', 0)}"
            f" diags={len(diags)}."
        )

        payload = {
            "artifacts": res.get("artifacts", []),
            "continuation": res.get("continuation", {}),
            "meta": {"stats": st, "diagnostics": diags},
        }

        _send({
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "result": {
                "content": [{"type": "text", "text": summary}],
                "structuredContent": payload,
                "continuation": payload["continuation"],
                "isError": False,
            },
        })

    except Exception as e:
        _send({
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "result": {"content": [{"type": "text", "text": str(e)}], "isError": True},
        })

def run_stdio_loop() -> None:
    print("mcp server ready", file=sys.stderr, flush=True)
    for line in sys.stdin:
        if not line:
            time.sleep(0.01)
            continue
        try:
            msg = json.loads(line.strip())
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

def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser("cobol-parser-mcp")
    ap.add_argument("--stdio", action="store_true")
    _ = ap.parse_args(argv)
    run_stdio_loop()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
