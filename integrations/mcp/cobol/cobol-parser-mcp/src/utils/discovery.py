# integrations/mcp/cobol/cobol-parser-mcp/src/utils/discovery.py
from __future__ import annotations
import os
from typing import Iterable, List, Tuple, Set

COBOL_EXT = {".cbl", ".cob", ".cobol"}
COPY_EXT = {".cpy", ".copy"}

def walk_sources(root: str) -> Iterable[Tuple[str, str, str]]:
    """
    Yield (abs_path, relpath, kind) where kind ∈ {"cobol","copybook"}.
    """
    for dirpath, _, files in os.walk(root):
        for fn in files:
            ext = os.path.splitext(fn)[1].lower()
            if ext in COBOL_EXT:
                abs_p = os.path.join(dirpath, fn)
                rel_p = os.path.relpath(abs_p, root)
                yield abs_p, rel_p, "cobol"
            elif ext in COPY_EXT:
                abs_p = os.path.join(dirpath, fn)
                rel_p = os.path.relpath(abs_p, root)
                yield abs_p, rel_p, "copybook"

def filter_paths(
    items: Iterable[Tuple[str, str, str]],
    allow_paths: List[str] | None,
) -> Iterable[Tuple[str, str, str]]:
    if not allow_paths:
        yield from items
        return
    allow_set: Set[str] = {p.strip().lstrip("./") for p in allow_paths if p.strip()}
    for abs_p, rel_p, kind in items:
        if rel_p in allow_set:
            yield abs_p, rel_p, kind
