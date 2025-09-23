from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

from .hashing import sha256_bytes

# File type buckets
COBOL_EXT = {".cbl", ".cob", ".cobol"}
COPY_EXT = {".cpy", ".copy"}
JCL_EXT = {".jcl"}
DDL_EXT = {".ddl", ".sql"}
BMS_EXT = {".bms", ".map"}

# Default directories to skip (can override via INDEX_SKIP_DIRS env)
DEFAULT_SKIP_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", ".pnpm-store", "vendor",
    "build", "dist", "target", "out", "bin", "obj",
    ".idea", ".vscode", ".venv", "venv", "__pycache__",
    ".pytest_cache", "coverage",
}

# Only include these kinds in the source_index (keeps the index small & relevant)
INCLUDED_KINDS = {"cobol", "copybook", "jcl", "ddl", "bms"}

def _classify_kind(p: Path, first_k_lines: List[str]) -> str:
    ext = p.suffix.lower()
    if ext in COBOL_EXT:
        return "cobol"
    if ext in COPY_EXT:
        return "copybook"
    if ext in JCL_EXT:
        return "jcl"
    if ext in DDL_EXT:
        return "ddl"
    if ext in BMS_EXT:
        return "bms"

    # Very light token hinting (kept for robustness, but we don't index "other")
    upper = "\n".join(first_k_lines[:200]).upper()
    if "IDENTIFICATION DIVISION." in upper or "ENVIRONMENT DIVISION." in upper:
        return "cobol"
    if upper.startswith("//"):
        return "jcl"
    return "other"

def _copybook_dir_hint(p: Path) -> bool:
    parts = {seg.lower() for seg in p.parts}
    return any(seg in parts for seg in {"cpy", "copy", "copylib", "copybooks", "includes"})

def _format_hint(first_k_lines: List[str]) -> str:
    if not first_k_lines:
        return "FIXED"
    early = sum(1 for ln in first_k_lines[:200] if ln[:7].strip() != "")
    very_long = sum(1 for ln in first_k_lines[:200] if len(ln.rstrip("\r\n")) > 100)
    if early > 10 or very_long > 10:
        return "FREE"
    return "FIXED"

def _read_head(path: Path, max_bytes: int = 4096) -> bytes:
    try:
        with path.open("rb") as f:
            return f.read(max_bytes)
    except Exception:
        return b""

def _first_lines(sample: bytes) -> List[str]:
    try:
        txt = sample.decode("utf-8", errors="ignore")
    except Exception:
        txt = ""
    return txt.splitlines()

def build_source_index(root: str) -> Dict[str, object]:
    """
    Build a compact source index focusing on COBOL-related inputs.
    Skips heavy, irrelevant directories by default (override with INDEX_SKIP_DIRS).
    """
    root_p = Path(root)
    files: List[Dict[str, object]] = []

    # Resolve skip dirs from env (comma-separated)
    skip_env = os.environ.get("INDEX_SKIP_DIRS", "")
    skip_dirs = {d.strip() for d in skip_env.split(",") if d.strip()} or DEFAULT_SKIP_DIRS

    for dirpath, dirnames, filenames in os.walk(root):
        # prune directories in-place for os.walk efficiency
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]

        for fn in filenames:
            abs_p = Path(dirpath) / fn
            if not abs_p.is_file():
                continue

            rel_p = abs_p.relative_to(root_p)
            sample = _read_head(abs_p, 4096)
            lines = _first_lines(sample)
            kind = _classify_kind(abs_p, lines)

            # Only index the kinds we care about (keeps payload small/fast)
            if kind not in INCLUDED_KINDS:
                continue

            # Stream sha256 for the files we actually index
            sha = _sha256_file(abs_p)
            meta: Dict[str, object] = {
                "relpath": str(rel_p).replace("\\", "/"),
                "size_bytes": abs_p.stat().st_size,
                "sha256": sha,
                "kind": kind,
            }
            if kind in {"cobol", "copybook"}:
                meta["language_hint"] = "COBOL"
                meta["format_hint"] = _format_hint(lines)
                meta["copybook_dir_hint"] = _copybook_dir_hint(rel_p.parent)
            files.append(meta)

    files.sort(key=lambda f: f["relpath"])  # deterministic order
    return {"root": str(root_p), "files": files}

def _sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 64), b""):
            h.update(chunk)
    return h.hexdigest()

def derive_copy_paths(index: Dict[str, object]) -> list[str]:
    """Pick candidate directories to search for copybooks (relative to root)."""
    files = index.get("files", [])
    parents = set()
    for f in files:
        if f.get("kind") == "copybook" or f.get("copybook_dir_hint"):
            from pathlib import Path as _P
            rel = _P(f["relpath"]).parent
            parents.add(str(rel).replace("\\", "/"))
    # shortest path first, cap to a sane number
    return sorted(parents, key=lambda s: (len(s), s))[:20]
