# integrations/mcp/cobol/cobol-parser-mcp/src/parser/normalizer.py
from __future__ import annotations
from typing import Any, Dict, List

def normalize_program(ast: Dict[str, Any], relpath: str, sha256: str) -> Dict[str, Any]:
    """Map adapter AST → cam.cobol.program payload (strict shape)."""
    paragraphs = ast.get("paragraphs") or []
    # deterministic sorts
    paragraphs = sorted(paragraphs, key=lambda p: p.get("name", ""))

    out_paragraphs: List[Dict[str, Any]] = []
    for p in paragraphs:
        performs = sorted(list({*p.get("performs", [])}))
        calls = p.get("calls") or []
        io_ops = p.get("io_ops") or []
        out_paragraphs.append({
            "name": p.get("name", ""),
            "performs": performs,
            "calls": calls,
            "io_ops": io_ops,
        })

    copybooks_used = sorted(list({*(ast.get("copybooks_used") or [])}))

    return {
        "program_id": ast.get("program_id", ""),
        "source": {"relpath": relpath, "sha256": sha256},
        "divisions": ast.get("divisions") or {"identification": {}, "environment": {}, "data": {}, "procedure": {}},
        "paragraphs": out_paragraphs,
        "copybooks_used": copybooks_used,
        "notes": [],
    }

def normalize_copybook(ast: Dict[str, Any], relpath: str, sha256: str) -> Dict[str, Any]:
    """Map adapter AST → cam.cobol.copybook payload."""
    return {
        "name": ast.get("name", ""),
        "source": {"relpath": relpath, "sha256": sha256},
        "items": ast.get("items") or [],
    }
