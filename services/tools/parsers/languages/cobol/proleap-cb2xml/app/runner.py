import json, subprocess, tempfile, pathlib
from typing import List

class JarError(RuntimeError):
    ...

def _run_java(jar_path: str, args: list[str]) -> str:
    try:
        res = subprocess.run(
            ["java", "-jar", jar_path, *args],
            capture_output=True, text=True, check=True
        )
        return res.stdout
    except subprocess.CalledProcessError as e:
        # Surface whichever stream carries the error payload
        msg = e.stderr or e.stdout or str(e)
        raise JarError(msg) from e

def run_proleap(proleap_jar: str, sources: List[str], dialect: str) -> list[dict]:
    """
    Write each source to a temp file and call the proleap-cli.jar.
    The CLI is expected to output JSON like: {"programs":[{...}, ...]}
    """
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        files = []
        for i, content in enumerate(sources):
            p = td / f"prog{i}.cbl"
            p.write_text(content)
            files.append(str(p))
        out = _run_java(proleap_jar, ["--dialect", dialect, "--format", "json", *files])
        data = json.loads(out) if out.strip() else {}
        return data.get("programs", [])

def run_cb2xml(cb2xml_jar: str, copybooks: List[str]) -> list[str]:
    """
    Convert each copybook to XML using cb2xml CLI:
      java -jar cb2xml.jar -c <copybook> -o <out.xml>
    """
    with tempfile.TemporaryDirectory() as td:
        td = pathlib.Path(td)
        xmls: list[str] = []
        for i, content in enumerate(copybooks):
            src = td / f"cpy{i}.cpy"
            out = td / f"cpy{i}.xml"
            src.write_text(content)
            _run_java(cb2xml_jar, ["-c", str(src), "-o", str(out)])
            xmls.append(out.read_text())
        return xmls
