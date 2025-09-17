# integrations/mcp/cobol/cobol-parser-mcp/src/parser/proleap_adapter.py
from __future__ import annotations

import os
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional


_PROGRAM_ID_RE = re.compile(r"^\s*PROGRAM-ID\.\s+([A-Za-z0-9_-]+)\s*\.?", re.IGNORECASE | re.MULTILINE)
_PARAGRAPH_RE  = re.compile(r"(?m)^\s{0,8}([A-Za-z0-9][A-Za-z0-9-]*)\s*\.\s*$")
_PERFORM_RE    = re.compile(r"\bPERFORM\s+([A-Za-z0-9][A-Za-z0-9-]*)\b", re.IGNORECASE)
_CALL_RE       = re.compile(r"\bCALL\s+(?:\"|'|)([A-Za-z0-9][A-Za-z0-9-]*)(?:\"|'|)\b", re.IGNORECASE)
_COPY_RE       = re.compile(r"\bCOPY\s+([A-Za-z0-9][A-Za-z0-9-]*)\b", re.IGNORECASE)
_IO_RE         = re.compile(r"\b(OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START)\b", re.IGNORECASE)


class ProLeapAdapter:
    """
    Adapter that *tries* to use ProLeap/cb2xml if available.
    If the jar is missing or errors out, we fall back to regex heuristics.
    """

    def __init__(self, jar_path: str | None = None) -> None:
        self.jar_path = jar_path or os.environ.get("PROLEAP_JAR")

    # ------------------------- Public API -------------------------

    def parse_program(self, text: str, relpath: str, dialect: str) -> Dict[str, Any]:
        xml_str = self._run_cb2xml(text, dialect)
        if xml_str:
            ast = self._from_cb2xml_program(xml_str, relpath)
            if ast:
                return ast

        program_id = self._guess_program_id(text) or self._program_id_from_filename(relpath)
        paragraphs = self._find_paragraphs(text)
        performs   = self._find_performs(text)
        calls      = self._find_calls(text)
        io_ops     = self._find_io_ops(text)
        copybooks  = self._find_copybooks(text)

        para_objs = [
            {"name": p, "performs": sorted(performs.get(p, [])), "calls": [], "io_ops": []}
            for p in sorted(set(paragraphs))
        ]
        return {
            "type": "program",
            "program_id": program_id,
            "divisions": {"identification": {}, "environment": {}, "data": {}, "procedure": {}},
            "paragraphs": para_objs if para_objs else [
                {"name": "MAIN", "performs": [], "calls": [], "io_ops": []}
            ],
            "copybooks_used": sorted(copybooks),
            "_calls_all": sorted(calls),
            "_io_ops_all": sorted(io_ops),
        }

    def parse_copybook(self, text: str, relpath: str, dialect: str) -> Dict[str, Any]:
        xml_str = self._run_cb2xml(text, dialect, is_copybook=True)
        name    = self._copybook_name_from_filename(relpath)

        if xml_str:
            items = self._from_cb2xml_copybook_items(xml_str)
            if items is not None:
                return {"type": "copybook", "name": name, "items": items}

        # Fallback heuristic: 01-level records
        items = []
        for rec in re.finditer(r"(?im)^\s*01\s+([A-Za-z0-9][A-Za-z0-9-]*)\b.*$", text):
            items.append({"level": "01", "name": rec.group(1).upper(), "picture": "", "children": []})

        if not items:
            items = [{"level": "01", "name": f"{name}-REC", "picture": "", "children": []}]

        return {"type": "copybook", "name": name, "items": items}

    # ------------------------- ProLeap helpers -------------------------

    def _run_cb2xml(self, cobol_src: str, dialect: str, is_copybook: bool = False) -> Optional[str]:
        jar = (self.jar_path or "").strip()
        if not jar or not os.path.isfile(jar):
            return None

        candidates = [["java", "-jar", jar, "-stdin"], ["java", "-jar", jar, "--stdin"]]
        env = os.environ.copy()
        env["COBOL_DIALECT"] = dialect

        for cmd in candidates:
            try:
                out = subprocess.check_output(
                    cmd,
                    input=cobol_src.encode("utf-8"),
                    stderr=subprocess.STDOUT,
                    env=env,
                )
                xml = out.decode("utf-8", errors="replace")
                if xml.strip().startswith("<"):
                    return xml
            except subprocess.CalledProcessError:
                continue
            except Exception:
                continue
        return None

    def _from_cb2xml_program(self, xml_str: str, relpath: str) -> Optional[Dict[str, Any]]:
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            return None

        program_id = self._find_xml_text(root, ["program-id", "programId", "PROGRAM-ID"]) \
                     or self._program_id_from_filename(relpath)

        para_names = set()
        for tag in ("paragraph", "paragraphName", "Paragraph", "para"):
            for node in root.findall(f".//{tag}"):
                name = (node.get("name") or node.text or "").strip()
                if name:
                    para_names.add(name.upper())

        paragraphs = [{"name": p, "performs": [], "calls": [], "io_ops": []} for p in sorted(para_names)]
        if not paragraphs:
            paragraphs = [{"name": "MAIN", "performs": [], "calls": [], "io_ops": []}]

        copybooks = set()
        for tag in ("copy", "copybook", "COPY"):
            for node in root.findall(f".//{tag}"):
                nm = (node.get("name") or node.text or "").strip()
                if nm:
                    copybooks.add(nm.upper())

        return {
            "type": "program",
            "program_id": program_id,
            "divisions": {"identification": {}, "environment": {}, "data": {}, "procedure": {}},
            "paragraphs": paragraphs,
            "copybooks_used": sorted(copybooks),
        }

    def _from_cb2xml_copybook_items(self, xml_str: str) -> Optional[List[Dict[str, Any]]]:
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            return None

        items: List[Dict[str, Any]] = []
        for node in root.findall(".//*"):
            level = (node.get("level") or "").strip()
            name  = (node.get("name") or node.get("fieldname") or (node.text or "")).strip()
            if level == "01" and name:
                items.append({"level": "01", "name": name.upper(), "picture": "", "children": []})

        return items if items else None

    # ------------------------- Heuristic helpers -------------------------

    def _program_id_from_filename(self, relpath: str) -> str:
        base = os.path.basename(relpath)
        name, _ = os.path.splitext(base)
        return name.upper()

    def _copybook_name_from_filename(self, relpath: str) -> str:
        base = os.path.basename(relpath)
        name, _ = os.path.splitext(base)
        return name.upper()

    def _guess_program_id(self, text: str) -> Optional[str]:
        m = _PROGRAM_ID_RE.search(text)
        return m.group(1).upper() if m else None

    def _find_paragraphs(self, text: str) -> List[str]:
        names = [m.group(1).upper() for m in _PARAGRAPH_RE.finditer(text)]
        seen, ordered = set(), []
        for n in names:
            if n not in seen:
                ordered.append(n)
                seen.add(n)
        return ordered

    def _find_performs(self, text: str) -> Dict[str, List[str]]:
        targets = [m.group(1).upper() for m in _PERFORM_RE.finditer(text)]
        return {"MAIN": sorted(set(targets))} if targets else {}

    def _find_calls(self, text: str) -> List[str]:
        return sorted({m.group(1).upper() for m in _CALL_RE.finditer(text)})

    def _find_copybooks(self, text: str) -> List[str]:
        return sorted({m.group(1).upper() for m in _COPY_RE.finditer(text)})

    def _find_io_ops(self, text: str) -> List[str]:
        return sorted({m.group(1).upper() for m in _IO_RE.finditer(text)})

    # ------------------------- XML util -------------------------

    def _find_xml_text(self, root: ET.Element, candidates: List[str]) -> Optional[str]:
        for tag in candidates:
            node = root.find(f".//{tag}")
            if node is not None:
                val = (node.text or node.get("name") or "").strip()
                if val:
                    return val.upper()
        return None
