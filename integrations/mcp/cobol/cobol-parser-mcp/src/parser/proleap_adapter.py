# integrations/mcp/cobol/cobol-parser-mcp/src/parser/proleap_adapter.py
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

# --- simple regex fallbacks ---
_PROGRAM_ID_RE = re.compile(r"^\s*PROGRAM-ID\.\s+([A-Za-z0-9_-]+)\s*\.?", re.IGNORECASE | re.MULTILINE)
_PARAGRAPH_RE  = re.compile(r"(?m)^\s{0,8}([A-Za-z0-9][A-Za-z0-9-]*)\s*\.\s*$")
_PERFORM_RE    = re.compile(r"\bPERFORM\s+([A-Za-z0-9][A-Za-z0-9-]*)\b", re.IGNORECASE)
_CALL_RE       = re.compile(r"\bCALL\s+(?:\"|'|)([A-Za-z0-9][A-Za-z0-9-]*)(?:\"|'|)\b", re.IGNORECASE)
_COPY_RE       = re.compile(r"\bCOPY\s+([A-Za-z0-9][A-Za-z0-9-]*)\b", re.IGNORECASE)
_IO_RE         = re.compile(r"\b(OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START)\b", re.IGNORECASE)


class ProLeapAdapter:
    """
    Program parsing: try ProLeap (classpath/CLI). Fallback to regex heuristics.
    Copybook parsing: try cb2xml (classpath/CLI). Fallback to 01-level heuristics.

    We *always* enrich per-paragraph performs/calls/io via lightweight regex over
    paragraph slices so you get edges even if the Java XML doesn’t carry them.
    """

    def __init__(self, jar_path: str | None = None) -> None:
        # kept for backwards compat; unused when we rely on classpaths
        self.jar_path = jar_path or os.environ.get("PROLEAP_JAR")

    # ------------------------- Public API -------------------------

    def parse_program(self, text: str, relpath: str, dialect: str) -> Dict[str, Any]:
        # 1) Try ProLeap
        xml_str = self._run_proleap(text, dialect)
        if xml_str:
            ast = self._from_proleap_program(xml_str, relpath)
            if ast:
                # enrich paragraph edges via regex on paragraph slices
                return self._enrich_program_with_regex(ast, text)

        # 2) Fallback: cb2xml can sometimes parse programs
        xml_str = self._run_cb2xml(text, dialect)
        if xml_str:
            ast = self._from_cb2xml_program(xml_str, relpath)
            if ast:
                return self._enrich_program_with_regex(ast, text)

        # 3) Final fallback: pure regex
        program_id = self._guess_program_id(text) or self._program_id_from_filename(relpath)
        paragraphs = self._find_paragraphs(text)
        para_objs = [
            {"name": p, "performs": [], "calls": [], "io_ops": []}
            for p in sorted(set(paragraphs))
        ]
        if not para_objs:
            para_objs = [{"name": "MAIN", "performs": [], "calls": [], "io_ops": []}]

        tmp_ast = {
            "type": "program",
            "program_id": program_id,
            "divisions": {"identification": {}, "environment": {}, "data": {}, "procedure": {}},
            "paragraphs": para_objs,
            "copybooks_used": sorted(self._find_copybooks(text)),
        }
        return self._enrich_program_with_regex(tmp_ast, text)

    def parse_copybook(self, text: str, relpath: str, dialect: str) -> Dict[str, Any]:
        xml_str = self._run_cb2xml(text, dialect, is_copybook=True)
        name = self._copybook_name_from_filename(relpath)

        if xml_str:
            items = self._from_cb2xml_copybook_items(xml_str)
            if items:
                return {"type": "copybook", "name": name, "items": items}

        # fallback: regex
        items = self._heuristic_copybook_items(text, name)
        return {"type": "copybook", "name": name, "items": items}

    # ------------------------- Java runners -------------------------

    def _run_proleap(self, cobol_src: str, dialect: str) -> Optional[str]:
        """
        Run ProLeap via classpath. We try:
          - env PROLEAP_CLASSPATH (or /opt/proleap/lib/*)
          - env PROLEAP_MAIN if set, else a list of candidate main classes.
        Accepts stdin if supported, else temp-file mode.
        """
        cp = os.environ.get("PROLEAP_CLASSPATH", "").strip() or "/opt/proleap/lib/*"
        mains = [os.environ.get("PROLEAP_MAIN", "").strip()] if os.environ.get("PROLEAP_MAIN") else []
        mains += [
            # Common candidates seen across versions/forks:
            "org.proleap.cobol.tool.CobolParserCLI",
            "org.proleap.cobol.tool.CLI",
            "org.proleap.cobol.CobolParserCLI",
            "org.proleap.cobol.tool.CobolMain",
        ]
        mains = [m for m in mains if m]

        env = os.environ.copy()
        env["COBOL_DIALECT"] = dialect

        # Try stdin first
        for main in mains:
            for flag in ("-stdin", "--stdin"):
                try:
                    out = subprocess.check_output(
                        ["java", "-cp", cp, main, flag],
                        input=cobol_src.encode("utf-8"),
                        stderr=subprocess.STDOUT,
                        env=env,
                    )
                    xml = out.decode("utf-8", errors="replace")
                    if xml.strip().startswith("<"):
                        return xml
                except Exception:
                    pass

        # Temp file fallback (some CLIs don’t take stdin)
        with tempfile.NamedTemporaryFile(prefix="proleap_in_", suffix=".cbl", delete=False) as tmp:
            tmp.write(cobol_src.encode("utf-8"))
            tmp.flush()
            in_path = tmp.name
        try:
            for main in mains:
                for args in (
                    [in_path],                # plain file → stdout xml (some builds)
                    ["-xml", in_path],
                    ["--xml", in_path],
                ):
                    try:
                        out = subprocess.check_output(
                            ["java", "-cp", cp, main, *args],
                            stderr=subprocess.STDOUT,
                            env=env,
                        )
                        xml = out.decode("utf-8", errors="replace")
                        if xml.strip().startswith("<"):
                            return xml
                    except Exception:
                        pass
        finally:
            try:
                os.remove(in_path)
            except Exception:
                pass

        return None

    def _run_cb2xml(self, cobol_src: str, dialect: str, is_copybook: bool = False) -> Optional[str]:
        """
        Run cb2xml via classpath. Works with cb2xml zips that ship libraries without a manifest.
        """
        cp = os.environ.get("CB2XML_CLASSPATH", "").strip() or "/opt/cb2xml/lib/*"
        mains = [os.environ.get("CB2XML_MAIN", "").strip()] if os.environ.get("CB2XML_MAIN") else []
        mains += ["net.sf.cb2xml.Cb2Xml", "net.sf.cb2xml.Cb2Xml2", "net.sf.cb2xml.cli.CLI"]
        mains = [m for m in mains if m]

        env = os.environ.copy()
        env["COBOL_DIALECT"] = dialect

        # Try stdin first
        for main in mains:
            for flag in ("-stdin", "--stdin"):
                try:
                    out = subprocess.check_output(
                        ["java", "-cp", cp, main, flag],
                        input=cobol_src.encode("utf-8"),
                        stderr=subprocess.STDOUT,
                        env=env,
                    )
                    xml = out.decode("utf-8", errors="replace")
                    if xml.strip().startswith("<"):
                        return xml
                except Exception:
                    pass

        # Temp file fallback
        with tempfile.NamedTemporaryFile(prefix="cb2xml_in_", suffix=".cob", delete=False) as tmp:
            tmp.write(cobol_src.encode("utf-8"))
            tmp.flush()
            in_path = tmp.name
        try:
            for main in mains:
                for args in (
                    [in_path],
                    ["-xml", in_path],
                    ["--xml", in_path],
                ):
                    try:
                        out = subprocess.check_output(
                            ["java", "-cp", cp, main, *args],
                            stderr=subprocess.STDOUT,
                            env=env,
                        )
                        xml = out.decode("utf-8", errors="replace")
                        if xml.strip().startswith("<"):
                            return xml
                    except Exception:
                        pass
        finally:
            try:
                os.remove(in_path)
            except Exception:
                pass

        return None

    # ------------------------- XML → AST -------------------------

    def _from_proleap_program(self, xml_str: str, relpath: str) -> Optional[Dict[str, Any]]:
        """
        ProLeap’s XML schema differs by version. Be defensive: pull just what we need.
        """
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            return None

        program_id = self._find_xml_text(root, ["program-id", "programId", "PROGRAM-ID"]) \
                     or self._program_id_from_filename(relpath)

        # paragraphs / sections
        para_names = set()
        for tag in ("paragraph", "Paragraph", "para", "paragraphName"):
            for node in root.findall(f".//{tag}"):
                nm = (node.get("name") or node.text or "").strip()
                if nm:
                    para_names.add(nm.upper())

        paragraphs = [{"name": p, "performs": [], "calls": [], "io_ops": []}
                      for p in sorted(para_names)] or [{"name": "MAIN", "performs": [], "calls": [], "io_ops": []}]

        # copybooks
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

    def _from_cb2xml_program(self, xml_str: str, relpath: str) -> Optional[Dict[str, Any]]:
        # very similar to ProLeap since we only consume light structure
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            return None

        program_id = self._find_xml_text(root, ["program-id", "programId", "PROGRAM-ID"]) \
                     or self._program_id_from_filename(relpath)

        para_names = set()
        for tag in ("paragraph", "Paragraph", "para", "paragraphName"):
            for node in root.findall(f".//{tag}"):
                nm = (node.get("name") or node.text or "").strip()
                if nm:
                    para_names.add(nm.upper())

        paragraphs = [{"name": p, "performs": [], "calls": [], "io_ops": []}
                      for p in sorted(para_names)] or [{"name": "MAIN", "performs": [], "calls": [], "io_ops": []}]

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
        return items or None

    # ------------------------- Regex enrichment -------------------------

    def _enrich_program_with_regex(self, ast: Dict[str, Any], full_text: str) -> Dict[str, Any]:
        """
        Take a skeleton program AST and fill per-paragraph performs/calls/io edges by
        slicing the source text into paragraph bodies and scanning each slice.
        """
        paragraphs: List[Dict[str, Any]] = ast.get("paragraphs") or []
        if not paragraphs:
            paragraphs = [{"name": "MAIN", "performs": [], "calls": [], "io_ops": []}]

        # Build paragraph spans from the source text
        # We find all paragraph labels & their byte/char offsets
        labels = []
        for m in _PARAGRAPH_RE.finditer(full_text):
            name = m.group(1).upper()
            labels.append((name, m.start(), m.end()))
        # map name -> (start, end) where end is start of next paragraph or EOF
        spans: Dict[str, tuple[int, int]] = {}
        for i, (name, start, _end) in enumerate(labels):
            next_start = len(full_text)
            if i + 1 < len(labels):
                next_start = labels[i + 1][1]
            spans[name] = (start, next_start)

        # Helper to slice text for a given paragraph
        def slice_for(name: str) -> str:
            s = spans.get(name.upper())
            if s:
                return full_text[s[0]:s[1]]
            # If we didn't find an explicit label span, scan whole file (best-effort)
            return full_text

        # Compute a global set of copybooks as a safety net (union with XML)
        copybooks_union = set(ast.get("copybooks_used") or [])
        copybooks_union |= set(self._find_copybooks(full_text))

        # Fill each paragraph
        out_paras: List[Dict[str, Any]] = []
        for p in paragraphs:
            name = (p.get("name") or "").upper()
            body = slice_for(name) if name else full_text

            # performs/calls/io within the paragraph body
            perf_targets = [m.group(1).upper() for m in _PERFORM_RE.finditer(body)]
            calls        = [m.group(1).upper() for m in _CALL_RE.finditer(body)]
            io_ops       = [m.group(1).upper() for m in _IO_RE.finditer(body)]

            out_paras.append({
                "name": name or (p.get("name") or ""),
                "performs": sorted(set(perf_targets)),
                "calls": sorted(set(calls)),
                "io_ops": sorted(set(io_ops)),
            })

        return {
            "type": "program",
            "program_id": ast.get("program_id", ""),
            "divisions": ast.get("divisions") or {"identification": {}, "environment": {}, "data": {}, "procedure": {}},
            "paragraphs": out_paras,
            "copybooks_used": sorted(copybooks_union),
        }

    # ------------------------- Heuristics -------------------------

    def _heuristic_copybook_items(self, text: str, name: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for rec in re.finditer(r"(?im)^\s*01\s+([A-Za-z0-9][A-Za-z0-9-]*)\b.*$", text):
            items.append({"level": "01", "name": rec.group(1).upper(), "picture": "", "children": []})
        if not items:
            items = [{"level": "01", "name": f"{name}-REC", "picture": "", "children": []}]
        return items

    # ------------------------- Utils -------------------------

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
                ordered.append(n); seen.add(n)
        return ordered

    def _find_calls(self, text: str) -> List[str]:
        return sorted({m.group(1).upper() for m in _CALL_RE.finditer(text)})

    def _find_copybooks(self, text: str) -> List[str]:
        return sorted({m.group(1).upper() for m in _COPY_RE.finditer(text)})

    def _find_io_ops(self, text: str) -> List[str]:
        return sorted({m.group(1).upper() for m in _IO_RE.finditer(text)})

    def _find_xml_text(self, root: Optional[ET.Element], candidates: List[str]) -> Optional[str]:
        if root is None:
            return None
        for tag in candidates:
            node = root.find(f".//{tag}")
            if node is not None:
                val = (node.text or node.get("name") or "").strip()
                if val:
                    return val.upper()
            for n in root.findall(".//*"):
                val = (n.get("name") or "").strip()
                if val and tag.lower() == "name":
                    return val.upper()
        return None
