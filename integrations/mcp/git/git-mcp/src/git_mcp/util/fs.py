from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable, List


def ensure_under_root(root: str, target: str) -> Path:
    root_p = Path(root).resolve()
    tgt_p = Path(target).resolve()
    if not str(tgt_p).startswith(str(root_p)):
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
    # de-dup
    uniq = []
    seen = set()
    for p in results:
        rp = str(p.resolve())
        if rp not in seen:
            uniq.append(p)
            seen.add(rp)
    return uniq
