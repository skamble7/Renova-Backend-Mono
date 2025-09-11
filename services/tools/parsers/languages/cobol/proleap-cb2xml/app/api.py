from fastapi import FastAPI, HTTPException, Request
from .models import ParseIn, ParseOut, CopybookIn, CopybookOut
from .runner import run_proleap, run_cb2xml, JarError
import os
import logging
from typing import Dict, Any, List
from uuid import uuid4
import shutil

logger = logging.getLogger("proleap.api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

PROLEAP_JAR = os.getenv("PROLEAP_JAR", "/opt/jars/proleap-cli.jar")
CB2XML_JAR  = os.getenv("CB2XML_JAR",  "/opt/jars/cb2xml.jar")

app = FastAPI(title="COBOL Parser (ProLeap + cb2xml)", version="1.0.0")


def _exists(p: str) -> bool:
    try:
        return os.path.exists(p)
    except Exception:
        return False


@app.get("/health")
def health() -> Dict[str, Any]:
    """Basic health + environment diagnostics."""
    java_path = shutil.which("java")
    info = {
        "ok": True,
        "service": "proleap-cb2xml",
        "version": app.version,
        "java_found": bool(java_path),
        "java_path": java_path,
        "proleap_jar": PROLEAP_JAR,
        "proleap_jar_exists": _exists(PROLEAP_JAR),
        "cb2xml_jar": CB2XML_JAR,
        "cb2xml_jar_exists": _exists(CB2XML_JAR),
    }
    # If any critical asset missing, still 200 but with ok=False to avoid failing eager health checks
    if not java_path or not _exists(PROLEAP_JAR) or not _exists(CB2XML_JAR):
        info["ok"] = False
    return info


def _summarize_sources(sources: List[str]) -> Dict[str, Any]:
    sizes = [len(s or "") for s in (sources or [])]
    lines = [len((s or "").splitlines()) for s in (sources or [])]
    sample = (sources[0] or "")[:500] if sources else ""
    return {"count": len(sources or []), "sizes": sizes[:10], "lines": lines[:10], "sample_head": sample}


@app.post("/parse", response_model=ParseOut)
def parse(body: ParseIn, request: Request):
    req_id = str(uuid4())
    summary = _summarize_sources(body.sources)
    logger.info("parse IN req=%s dialect=%s sources=%s", req_id, body.dialect, summary)

    try:
        programs = run_proleap(PROLEAP_JAR, body.sources, body.dialect)
        logger.info("parse OK req=%s programs=%d", req_id, len(programs))
        return {"programs": programs}
    except JarError as e:
        # Log full details server-side, return concise message to client
        logger.exception("parse JarError req=%s: %s", req_id, e)
        detail = {"error": "proleap failed", "message": str(e), "req_id": req_id}
        raise HTTPException(status_code=500, detail=detail)
    except Exception as e:
        logger.exception("parse unexpected error req=%s", req_id)
        detail = {"error": "unexpected", "message": str(e), "req_id": req_id}
        raise HTTPException(status_code=500, detail=detail)


# Aliases so clients that try versioned paths won't 404
@app.post("/v1/parse", response_model=ParseOut, include_in_schema=False)
def parse_v1(body: ParseIn, request: Request):
    return parse(body, request)


@app.post("/api/v1/parse", response_model=ParseOut, include_in_schema=False)
def parse_api_v1(body: ParseIn, request: Request):
    return parse(body, request)


@app.post("/copybook_to_xml", response_model=CopybookOut)
def copybook_to_xml(body: CopybookIn, request: Request):
    req_id = str(uuid4())
    logger.info("copybook_to_xml IN req=%s count=%d", req_id, len(body.copybooks or []))
    try:
        xml_docs = run_cb2xml(CB2XML_JAR, body.copybooks)
        logger.info("copybook_to_xml OK req=%s docs=%d", req_id, len(xml_docs))
        return {"xmlDocs": xml_docs}
    except JarError as e:
        logger.exception("copybook_to_xml JarError req=%s: %s", req_id, e)
        detail = {"error": "cb2xml failed", "message": str(e), "req_id": req_id}
        raise HTTPException(status_code=500, detail=detail)
    except Exception as e:
        logger.exception("copybook_to_xml unexpected error req=%s", req_id)
        detail = {"error": "unexpected", "message": str(e), "req_id": req_id}
        raise HTTPException(status_code=500, detail=detail)


# Aliases for copybook endpoint as well (optional)
@app.post("/v1/copybook_to_xml", response_model=CopybookOut, include_in_schema=False)
def copybook_to_xml_v1(body: CopybookIn, request: Request):
    return copybook_to_xml(body, request)


@app.post("/api/v1/copybook_to_xml", response_model=CopybookOut, include_in_schema=False)
def copybook_to_xml_api_v1(body: CopybookIn, request: Request):
    return copybook_to_xml(body, request)
