import json
import subprocess
import tempfile
import pathlib
import logging
import os
import shutil
import time
from typing import List, Tuple

logger = logging.getLogger("proleap.runner")

class JarError(RuntimeError):
    ...


def _exists(p: str) -> bool:
    try:
        return os.path.exists(p)
    except Exception:
        return False


def _run_java(jar_path: str, args: list[str]) -> Tuple[str, str, int]:
    """
    Run a jar and return (stdout, stderr, rc).
    We DO NOT raise here; callers decide whether to treat nonzero as fatal.
    """
    java_path = shutil.which("java")
    logger.info(
        "java check: found=%s path=%s jar=%s exists=%s",
        bool(java_path), java_path, jar_path, _exists(jar_path)
    )

    if not java_path:
        raise JarError("Java runtime not found in PATH")

    if not _exists(jar_path):
        raise JarError(f"Jar not found: {jar_path}")

    cmd = [java_path, "-jar", jar_path, *args]
    logger.info("exec: %s", " ".join(cmd))

    res = subprocess.run(cmd, capture_output=True, text=True)
    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    if out:
        logger.debug("exec stdout (head 500): %s", out[:500])
    if err:
        logger.debug("exec stderr (head 500): %s", err[:500])
    return out, err, res.returncode


def run_proleap(proleap_jar: str, sources: List[str], dialect: str) -> list[dict]:
    """
    Write each source to a temp file and call the proleap-cli.jar.
    The CLI is expected to output JSON like: {"programs":[{...}, ...]}
    Robust to empty/non-JSON output; raises JarError with context for the API layer to decide.
    """
    t0 = time.perf_counter()
    logger.info("run_proleap: dialect=%s sources=%d", dialect, len(sources or []))

    if not sources:
        logger.info("run_proleap: empty sources -> returning []")
        return []

    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        files = []
        for i, content in enumerate(sources or []):
            p = td / f"prog{i}.cbl"
            # tolerate encoding issues
            p.write_text(content or "", encoding="utf-8", errors="ignore")
            files.append(str(p))
        logger.info("run_proleap: temp_files=%s", files)

        out, err, rc = _run_java(proleap_jar, ["--dialect", dialect, "--format", "json", *files])

        if rc != 0:
            # Prefer stderr for context
            msg = (err or out or f"proleap-cli exited rc={rc}")[:2000]
            raise JarError(msg)

        if not out:
            raise JarError("proleap-cli produced empty output")

        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            head = out[:2000]
            raise JarError(f"proleap-cli returned non-JSON (head): {head}")

        programs = data.get("programs", [])
        logger.info("run_proleap: parsed programs=%d (%.3fs)", len(programs), time.perf_counter() - t0)
        return programs


def run_cb2xml(cb2xml_jar: str, copybooks: List[str]) -> list[str]:
    """
    Convert each copybook to XML using cb2xml CLI:
      java -jar cb2xml.jar -c <copybook> -o <out.xml>
    """
    t0 = time.perf_counter()
    logger.info("run_cb2xml: copybooks=%d", len(copybooks or []))

    if not copybooks:
        logger.info("run_cb2xml: empty copybooks -> returning []")
        return []

    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        xmls: list[str] = []
        for i, content in enumerate(copybooks or []):
            src = td / f"cpy{i}.cpy"
            out = td / f"cpy{i}.xml"
            src.write_text(content or "", encoding="utf-8", errors="ignore")
            _out, _err, rc = _run_java(cb2xml_jar, ["-c", str(src), "-o", str(out)])
            if rc != 0:
                # Let the API layer accumulate non-fatal errors if desired
                raise JarError((_err or _out or f"cb2xml exited rc={rc}")[:2000])
            xmls.append(out.read_text(encoding="utf-8", errors="ignore"))

        logger.info("run_cb2xml: produced xml_docs=%d (%.3fs)", len(xmls), time.perf_counter() - t0)
        return xmls
