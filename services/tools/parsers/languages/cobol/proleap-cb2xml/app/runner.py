import json
import subprocess
import tempfile
import pathlib
import logging
import os
import shutil
from typing import List

logger = logging.getLogger("proleap.runner")

class JarError(RuntimeError):
    ...


def _exists(p: str) -> bool:
    try:
        return os.path.exists(p)
    except Exception:
        return False


def _run_java(jar_path: str, args: list[str]) -> str:
    java_path = shutil.which("java")
    logger.info("java check: found=%s path=%s jar=%s exists=%s",
                bool(java_path), java_path, jar_path, _exists(jar_path))

    if not java_path:
        raise JarError("Java runtime not found in PATH")

    if not _exists(jar_path):
        raise JarError(f"Jar not found: {jar_path}")

    cmd = [java_path, "-jar", jar_path, *args]
    logger.info("exec: %s", " ".join(cmd))

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        stdout = (res.stdout or "").strip()
        if stdout:
            # log only a head for very large outputs
            logger.debug("exec stdout (head 500): %s", stdout[:500])
        if res.stderr:
            logger.debug("exec stderr (head 500): %s", res.stderr[:500])
        return res.stdout
    except subprocess.CalledProcessError as e:
        out = (e.stdout or "").strip()
        err = (e.stderr or "").strip()
        # Truncate to avoid blowing up logs
        out_h = out[:2000]
        err_h = err[:2000]
        logger.error("exec failed rc=%s\nSTDOUT(head): %s\nSTDERR(head): %s", e.returncode, out_h, err_h)
        # Prefer stderr content for error detail
        msg = err or out or str(e)
        raise JarError(msg) from e


def run_proleap(proleap_jar: str, sources: List[str], dialect: str) -> list[dict]:
    """
    Write each source to a temp file and call the proleap-cli.jar.
    The CLI is expected to output JSON like: {"programs":[{...}, ...]}
    """
    logger.info("run_proleap: dialect=%s sources=%d", dialect, len(sources or []))
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        files = []
        for i, content in enumerate(sources or []):
            p = td / f"prog{i}.cbl"
            # tolerate encoding issues
            p.write_text(content or "", encoding="utf-8", errors="ignore")
            files.append(str(p))
        logger.info("run_proleap: temp_files=%s", files)

        out = _run_java(proleap_jar, ["--dialect", dialect, "--format", "json", *files])
        data = json.loads(out) if (out or "").strip() else {}
        programs = data.get("programs", [])
        logger.info("run_proleap: parsed programs=%d", len(programs))
        return programs


def run_cb2xml(cb2xml_jar: str, copybooks: List[str]) -> list[str]:
    """
    Convert each copybook to XML using cb2xml CLI:
      java -jar cb2xml.jar -c <copybook> -o <out.xml>
    """
    logger.info("run_cb2xml: copybooks=%d", len(copybooks or []))
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        xmls: list[str] = []
        for i, content in enumerate(copybooks or []):
            src = td / f"cpy{i}.cpy"
            out = td / f"cpy{i}.xml"
            src.write_text(content or "", encoding="utf-8", errors="ignore")
            _run_java(cb2xml_jar, ["-c", str(src), "-o", str(out)])
            xmls.append(out.read_text(encoding="utf-8", errors="ignore"))
        logger.info("run_cb2xml: produced xml_docs=%d", len(xmls))
        return xmls
