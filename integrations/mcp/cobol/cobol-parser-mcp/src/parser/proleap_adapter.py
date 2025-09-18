from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from functools import lru_cache



# --- simple regex fallbacks ---
_PROGRAM_ID_RE = re.compile(r"^\s*PROGRAM-ID\.\s+([A-Za-z0-9_-]+)\s*\.?", re.IGNORECASE | re.MULTILINE)
_PARAGRAPH_RE  = re.compile(r"(?m)^\s{0,8}([A-Za-z0-9][A-Za-z0-9-]*)\s*\.\s*$")
_PERFORM_RE    = re.compile(r"\bPERFORM\s+([A-Za-z0-9][A-Za-z0-9-]*)\b", re.IGNORECASE)
_CALL_RE       = re.compile(r"\bCALL\s+(?:\"|'|)([A-Za-z0-9][A-Za-z0-9-]*)(?:\"|'|)\b", re.IGNORECASE)
_COPY_RE       = re.compile(r"\bCOPY\s+([A-Za-z0-9][A-Za-z0-9-]*)\b", re.IGNORECASE)
_IO_RE         = re.compile(r"\b(OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START)\b", re.IGNORECASE)

@lru_cache(maxsize=1024)
def _read_copy_candidate(abs_path: str) -> Optional[str]:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None

def _expand_copys(text: str, relpath: str, copy_dirs: List[str]) -> str:
    """
    Very small include preprocessor for `COPY NAME.` lines.
    Supports: bare `COPY NAME.` on its own line.
    Does NOT implement REPLACING (we can add common patterns later).
    """
    if not copy_dirs:
        return text

    lines = text.splitlines(keepends=True)
    out: List[str] = []
    for ln in lines:
        m = _COPY_RE.search(ln)
        if m and ln.strip().upper().endswith("."):
            name = m.group(1)
            # try NAME.cpy / NAME.CPY / NAME.copy
            candidates = []
            for d in copy_dirs:
                for ext in (".cpy", ".CPY", ".copy", ".COPY"):
                    candidates.append(os.path.join(d, f"{name}{ext}"))
            included = None
            for c in candidates:
                s = _read_copy_candidate(c)
                if s is not None:
                    included = s
                    break
            if included is not None:
                # naive include; retain a marker comment
                out.append(f"      *COPY {name}*.\n")
                out.append(included if included.endswith("\n") else included + "\n")
                continue
        out.append(ln)
    return "".join(out)

# --- neutralize unsupported EXEC blocks for ProLeap (IMS, DLI, etc.) ---
# Replace EXEC DLI/IMS ... END-EXEC. (single statement or multiline) with a no-op.
_EXEC_BLOCKS = [
    re.compile(r"(?is)^\s*EXEC\s+DLI\b.*?END-EXEC\s*\.", re.MULTILINE),
    re.compile(r"(?is)^\s*EXEC\s+IMS\b.*?END-EXEC\s*\.", re.MULTILINE),
]
def _neutralize_unsupported_execs(src: str) -> str:
    out = src
    for pat in _EXEC_BLOCKS:
        out = pat.sub("    CONTINUE.", out)
    return out


def _should_dump(dump_raw_flag: bool) -> bool:
    # If RAW_AST_DUMP_DIR is set, we default to dumping even if caller didn't pass dump_raw=True.
    return dump_raw_flag or bool(os.environ.get("RAW_AST_DUMP_DIR"))


def _dump_path_for(relpath: str, tool: str, suffix: str) -> Path:
    root = os.environ.get("RAW_AST_DUMP_DIR") or "/tmp/proleap_raw"
    safe_rel = relpath.strip("/").replace("\\", "/")
    return Path(root) / f"{safe_rel}.{tool}{suffix}"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _dump_text(path: Path, content: str) -> None:
    _ensure_parent(path)
    path.write_text(content, encoding="utf-8", errors="replace")


def _dump_json(path: Path, obj: Any) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_io_ops(tokens: List[str]) -> List[Dict[str, Any]]:
    # Schema expects objects; minimally provide operation + nullable target.
    return [{"operation": tok.upper(), "target": None} for tok in tokens]


class ProLeapAdapter:
    """
    Program parsing: try ProLeap (classpath/CLI). Fallback to regex heuristics.
    Copybook parsing: try cb2xml (classpath/CLI). Fallback to 01-level heuristics.

    Debug dumps:
      - Set env RAW_AST_DUMP_DIR=/mnt/work/.renova/debug/raw-ast (or anywhere)
      - Success XML → <relpath>.<tool>.xml
      - If CLI output isn't XML, we still dump it as <relpath>.<tool>.txt
      - We also capture <relpath>.<tool>.attempts.json with the tried commands.
    """

    def __init__(self, jar_path: str | None = None) -> None:
        # kept for backwards compat; unused when we rely on classpaths
        self.jar_path = jar_path or os.environ.get("PROLEAP_JAR")

    # ------------------------- Public API -------------------------

    def parse_program(
        self,
        text: str,
        relpath: str,
        dialect: str,
        dump_raw: bool = False,
        dump_dir: Optional[str] = None,  # kept for API compatibility (unused; we prefer env)
        copy_paths: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        want_dump = _should_dump(dump_raw)

        if copy_paths:
            try:
                text = _expand_copys(text, relpath, copy_paths)
            except Exception:
                pass

        xml_str, attempts, raw_out = self._run_proleap(text, dialect, relpath)
        if want_dump:
            _dump_json(_dump_path_for(relpath, "proleap", ".attempts.json"), attempts)
            if xml_str:
                _dump_text(_dump_path_for(relpath, "proleap", ".xml"), xml_str)
            elif raw_out:
                _dump_text(_dump_path_for(relpath, "proleap", ".txt"), raw_out)

        if xml_str:
            ast = self._from_proleap_program(xml_str, relpath)
            if ast:
                if want_dump:
                    ast["_raw_dump_path"] = str(_dump_path_for(relpath, "proleap", ".xml"))
                # never emit "notes" unless schema allows it
                ast.pop("notes", None)
                return ast

        # fallback: cb2xml sometimes parses programs too; try it second
        xml_str, attempts, raw_out = self._run_cb2xml(text, dialect, relpath, is_copybook=False)
        if want_dump:
            _dump_json(_dump_path_for(relpath, "cb2xml_prog", ".attempts.json"), attempts)
            if xml_str:
                _dump_text(_dump_path_for(relpath, "cb2xml_prog", ".xml"), xml_str)
            elif raw_out:
                _dump_text(_dump_path_for(relpath, "cb2xml_prog", ".txt"), raw_out)

        if xml_str:
            ast = self._from_cb2xml_program(xml_str, relpath)
            if ast:
                if want_dump:
                    ast["_raw_dump_path"] = str(_dump_path_for(relpath, "cb2xml_prog", ".xml"))
                ast.pop("notes", None)
                return ast

        # final fallback: regex
        program_id = self._guess_program_id(text) or self._program_id_from_filename(relpath)
        paragraphs = self._find_paragraphs(text)
        performs   = self._find_performs(text)
        calls      = self._find_calls(text)
        io_ops_all = self._find_io_ops(text)
        copybooks  = self._find_copybooks(text)

        para_objs = [
            {
                "name": p,
                "performs": sorted(performs.get(p, [])),
                "calls": [],
                # We don't have paragraph-scoped IO today; keep empty array (schema allows []).
                "io_ops": [],
            }
            for p in sorted(set(paragraphs))
        ] or [{"name": "MAIN", "performs": [], "calls": [], "io_ops": []}]

        ast: Dict[str, Any] = {
            "type": "program",
            "program_id": program_id,
            "divisions": {"identification": {}, "environment": {}, "data": {}, "procedure": {}},
            "paragraphs": para_objs,
            "copybooks_used": sorted(copybooks),
            # rollup fields for debugging/consumers; keep underscore-namespaced
            "_calls_all": sorted(calls),
            "_io_ops_all": _normalize_io_ops(sorted(set(io_ops_all))),
        }
        # ensure no stray "notes"
        ast.pop("notes", None)
        return ast

    def parse_copybook(
        self,
        text: str,
        relpath: str,
        dialect: str,
        dump_raw: bool = False,
        dump_dir: Optional[str] = None,  # kept for API compatibility (unused; we prefer env)
    ) -> Dict[str, Any]:
        want_dump = _should_dump(dump_raw)

        xml_str, attempts, raw_out = self._run_cb2xml(text, dialect, relpath, is_copybook=True)
        if want_dump:
            _dump_json(_dump_path_for(relpath, "cb2xml_copy", ".attempts.json"), attempts)
            if xml_str:
                _dump_text(_dump_path_for(relpath, "cb2xml_copy", ".xml"), xml_str)
            elif raw_out:
                _dump_text(_dump_path_for(relpath, "cb2xml_copy", ".txt"), raw_out)

        name = self._copybook_name_from_filename(relpath)

        if xml_str:
            items = self._from_cb2xml_copybook_items(xml_str)
            if items:
                res: Dict[str, Any] = {"type": "copybook", "name": name, "items": items}
                if want_dump:
                    res["_raw_dump_path"] = str(_dump_path_for(relpath, "cb2xml_copy", ".xml"))
                # never emit "notes"
                res.pop("notes", None)
                return res

        # fallback: regex
        items = self._heuristic_copybook_items(text, name)
        return {"type": "copybook", "name": name, "items": items}

    # ------------------------- Java runners -------------------------

    def _run_proleap(self, cobol_src: str, dialect: str, relpath: str) -> Tuple[Optional[str], list, str]:
        """
        Run ProLeap via classpath. Prefer the bridge CLI (com.renova.proleap.CLI).
        Accepts stdin if supported, else temp-file mode.

        Returns: (xml_or_none, attempts[], raw_combined_text)
        """
        attempts: List[Dict[str, Any]] = []
        combined_text_out = ""

        # Prefer the bridge jar & main.
        cp = (os.environ.get("PROLEAP_CLASSPATH") or "/opt/proleap/lib/proleap-cli-bridge.jar").strip()
        main = (os.environ.get("PROLEAP_MAIN") or "com.renova.proleap.CLI").strip()
        mains = [m for m in [main] if m]

        env = os.environ.copy()
        env["COBOL_DIALECT"] = dialect

        def _try_stdin(src: str, tag: str) -> Tuple[Optional[str], str]:
            cmd = ["java", "-cp", cp, mains[0], "-stdin"]
            attempts.append({"mode": "stdin", "cmd": cmd, tag: True})
            try:
                out = subprocess.check_output(cmd, input=src.encode("utf-8"),
                                              stderr=subprocess.STDOUT, env=env)
                s = out.decode("utf-8", errors="replace")
                return (s if s.strip().startswith("<") else None, f"\n# {cmd}\n{s}\n")
            except subprocess.CalledProcessError as e:
                msg = e.output.decode("utf-8", errors="replace") if e.output else str(e)
                return (None, f"\n# {cmd} FAILED (exit {e.returncode}):\n{msg}\n")
            except Exception as e:
                return (None, f"\n# {cmd} FAILED (exception): {e}\n")

        def _try_file(src: str, tag: str) -> Tuple[Optional[str], str]:
            out_log = ""
            with tempfile.NamedTemporaryFile(prefix="proleap_in_", suffix=".cbl", delete=False) as tmp:
                tmp.write(src.encode("utf-8")); tmp.flush()
                in_path = tmp.name
            try:
                for args in ([in_path], ["-xml", in_path], ["--xml", in_path]):
                    cmd = ["java", "-cp", cp, mains[0], *args]
                    attempts.append({"mode": "file", "cmd": cmd, tag: True})
                    try:
                        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, env=env)
                        s = out.decode("utf-8", errors="replace")
                        out_log += f"\n# {cmd}\n{s}\n"
                        if s.strip().startswith("<"):
                            return s, out_log
                    except subprocess.CalledProcessError as e:
                        msg = e.output.decode("utf-8", errors="replace") if e.output else str(e)
                        out_log += f"\n# {cmd} FAILED (exit {e.returncode}):\n{msg}\n"
                    except Exception as e:
                        out_log += f"\n# {cmd} FAILED (exception): {e}\n"
            finally:
                try:
                    os.remove(in_path)
                except Exception:
                    pass
            return None, out_log

        # 1) Try original source via stdin, then file
        s, log = _try_stdin(cobol_src, "original")
        combined_text_out += log
        if s:
            return s, attempts, combined_text_out

        s, log = _try_file(cobol_src, "original")
        combined_text_out += log
        if s:
            return s, attempts, combined_text_out

        # 2) If we saw IMS markers (or proactively), sanitize and retry once
        if any(p.search(cobol_src) for p in _EXEC_BLOCKS) or "EXEC DLI" in cobol_src.upper() or "EXEC IMS" in cobol_src.upper() or "EXEC DLI" in combined_text_out.upper() or "EXEC IMS" in combined_text_out.upper():
            sanitized = _neutralize_unsupported_execs(cobol_src)
            s, log = _try_stdin(sanitized, "sanitized_exec")
            combined_text_out += log
            if s:
                return s, attempts, combined_text_out + "\n[SANITIZED RETRY OK]"

            s, log = _try_file(sanitized, "sanitized_exec")
            combined_text_out += log
            if s:
                return s, attempts, combined_text_out + "\n[SANITIZED RETRY OK]"

        return None, attempts, combined_text_out.strip()

    def _run_cb2xml(self, cobol_src: str, dialect: str, relpath: str, is_copybook: bool) -> tuple[Optional[str], list, str]:
        attempts: List[Dict[str, Any]] = []
        combined_text_out = ""

        cp = os.environ.get("CB2XML_CLASSPATH", "").strip() or "/opt/cb2xml/lib/*"
        mains = [os.environ.get("CB2XML_MAIN", "").strip()] if os.environ.get("CB2XML_MAIN") else []
        mains += ["net.sf.cb2xml.Cb2Xml", "net.sf.cb2xml.Cb2Xml2", "net.sf.cb2xml.cli.CLI"]
        mains = [m for m in mains if m]

        env = os.environ.copy()
        env["COBOL_DIALECT"] = dialect

        # Try stdin first
        for main in mains:
            for flag in ("-stdin", "--stdin"):
                cmd = ["java", "-cp", cp, main, flag]
                attempts.append({"mode": "stdin", "cmd": cmd, "is_copybook": is_copybook})
                try:
                    out = subprocess.check_output(
                        cmd, input=cobol_src.encode("utf-8"),
                        stderr=subprocess.STDOUT, env=env
                    )
                    s = out.decode("utf-8", errors="replace")
                    combined_text_out += f"\n# {cmd}\n{s}\n"
                    if s.strip().startswith("<"):
                        return s, attempts, combined_text_out
                except subprocess.CalledProcessError as e:
                    msg = e.output.decode("utf-8", errors="replace") if e.output else str(e)
                    combined_text_out += f"\n# {cmd} FAILED (exit {e.returncode}):\n{msg}\n"
                except Exception as e:
                    combined_text_out += f"\n# {cmd} FAILED (exception): {e}\n"

        # Temp file fallback
        suffix = ".cpy" if is_copybook else ".cob"
        with tempfile.NamedTemporaryFile(prefix="cb2xml_in_", suffix=suffix, delete=False) as tmp:
            tmp.write(cobol_src.encode("utf-8"))
            tmp.flush()
            in_path = tmp.name
        try:
            for main in mains:
                for args in ([in_path], ["-xml", in_path], ["--xml", in_path]):
                    cmd = ["java", "-cp", cp, main, *args]
                    attempts.append({"mode": "file", "cmd": cmd, "is_copybook": is_copybook})
                    try:
                        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, env=env)
                        s = out.decode("utf-8", errors="replace")
                        combined_text_out += f"\n# {cmd}\n{s}\n"
                        if s.strip().startswith("<"):
                            return s, attempts, combined_text_out
                    except subprocess.CalledProcessError as e:
                        msg = e.output.decode("utf-8", errors="replace") if e.output else str(e)
                        combined_text_out += f"\n# {cmd} FAILED (exit {e.returncode}):\n{msg}\n"
                    except Exception as e:
                        combined_text_out += f"\n# {cmd} FAILED (exception): {e}\n"
        finally:
            try:
                os.remove(in_path)
            except Exception:
                pass

        return None, attempts, combined_text_out.strip()

    # ------------------------- XML → AST -------------------------

    def _from_proleap_program(self, xml_str: str, relpath: str) -> Optional[Dict[str, Any]]:
        """
        ProLeap XML varies by version; be defensive.
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
                nm = (node.get("name") or (node.text or "")).strip()
                if nm:
                    para_names.add(nm.upper())

        paragraphs = [{"name": p, "performs": [], "calls": [], "io_ops": []}
                      for p in sorted(para_names)] or [{"name": "MAIN", "performs": [], "calls": [], "io_ops": []}]

        # copybooks
        copybooks = set()
        for tag in ("copy", "copybook", "COPY"):
            for node in root.findall(f".//{tag}"):
                nm = (node.get("name") or (node.text or "")).strip()
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
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            return None

        program_id = self._find_xml_text(root, ["program-id", "programId", "PROGRAM-ID"]) \
                     or self._program_id_from_filename(relpath)

        para_names = set()
        for tag in ("paragraph", "Paragraph", "para", "paragraphName"):
            for node in root.findall(f".//{tag}"):
                nm = (node.get("name") or (node.text or "")).strip()
                if nm:
                    para_names.add(nm.upper())

        paragraphs = [{"name": p, "performs": [], "calls": [], "io_ops": []}
                      for p in sorted(para_names)] or [{"name": "MAIN", "performs": [], "calls": [], "io_ops": []}]

        copybooks = set()
        for tag in ("copy", "copybook", "COPY"):
            for node in root.findall(f".//{tag}"):
                nm = (node.get("name") or (node.text or "")).strip()
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

    def _find_performs(self, text: str) -> Dict[str, List[str]]:
        targets = [m.group(1).upper() for m in _PERFORM_RE.finditer(text)]
        return {"MAIN": sorted(set(targets))} if targets else {}

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
