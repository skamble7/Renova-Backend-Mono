# integrations/mcp/git/git-mcp/src/git_mcp/util/fs.py
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable, List


def ensure_under_root(root: str, target: str) -> Path:
    """
    Resolve `target` so it is guaranteed to be inside `root`.

    - If `target` is relative, interpret it under `root`.
    - If `target` is absolute, it must still live inside `root`.
    - Allows exact match with `root` or any descendant.
    """
    root_p = Path(root).resolve()
    tgt_p = Path(target)

    # Interpret relative paths under the root
    if not tgt_p.is_absolute():
        tgt_p = root_p / tgt_p

    # Resolve symlinks/.. and normalise
    tgt_p = tgt_p.resolve()

    # Reject escapes (use relative_to to avoid simple prefix checks)
    try:
        # will raise ValueError if tgt_p is not inside root_p
        tgt_p.relative_to(root_p)
    except ValueError:
        raise ValueError(f"path escapes root: {target}")

    return tgt_p


def sha256_of_file(p: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def list_files(root: str, globs: Iterable[str]) -> List[Path]:
    root_p = Path(root)
    if not root_p.exists():
        return []

    if not globs:
        return [p for p in root_p.rglob("*") if p.is_file()]

    results: List[Path] = []
    for pattern in globs:
        results.extend([p for p in root_p.rglob(pattern) if p.is_file()])

    # de-dup by real path
    uniq: List[Path] = []
    seen = set()
    for p in results:
        rp = str(p.resolve())
        if rp not in seen:
            uniq.append(p)
            seen.add(rp)
    return uniq
