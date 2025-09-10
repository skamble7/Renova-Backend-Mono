from fastapi import FastAPI, HTTPException
from .models import ParseIn, ParseOut, CopybookIn, CopybookOut
from .runner import run_proleap, run_cb2xml, JarError
import os

PROLEAP_JAR = os.getenv("PROLEAP_JAR", "/opt/jars/proleap-cli.jar")
CB2XML_JAR  = os.getenv("CB2XML_JAR",  "/opt/jars/cb2xml.jar")

app = FastAPI(title="COBOL Parser (ProLeap + cb2xml)", version="1.0.0")

@app.post("/parse", response_model=ParseOut)
def parse(body: ParseIn):
    try:
        programs = run_proleap(PROLEAP_JAR, body.sources, body.dialect)
        return {"programs": programs}
    except JarError as e:
        raise HTTPException(status_code=500, detail=f"proleap failed: {e}")

@app.post("/copybook_to_xml", response_model=CopybookOut)
def copybook_to_xml(body: CopybookIn):
    try:
        xml_docs = run_cb2xml(CB2XML_JAR, body.copybooks)
        return {"xmlDocs": xml_docs}
    except JarError as e:
        raise HTTPException(status_code=500, detail=f"cb2xml failed: {e}")
