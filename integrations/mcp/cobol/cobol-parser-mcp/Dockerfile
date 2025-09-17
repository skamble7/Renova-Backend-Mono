# integrations/mcp/cobol/cobol-parser-mcp/Dockerfile
FROM python:3.12-slim

# JRE + essentials
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-21-jre-headless tini ca-certificates bash \
    coreutils unzip \
 && rm -rf /var/lib/apt/lists/*
 

WORKDIR /opt/renova/tools/cobol-parser

# ---- add cb2xml jars (classpath-based)
RUN mkdir -p /opt/cb2xml/lib
COPY vendor/cb2xml/lib/*.jar /opt/cb2xml/lib/
RUN chmod 0644 /opt/cb2xml/lib/*.jar || true

# ---- add ProLeap jars (classpath-based)
RUN mkdir -p /opt/proleap/lib
COPY vendor/proleap/lib/*.jar /opt/proleap/lib/
RUN chmod 0644 /opt/proleap/lib/*.jar || true

# Classpath envs the adapter will use (can be overridden in mcp.json)
ENV CB2XML_CLASSPATH="/opt/cb2xml/lib/*" \
    CB2XML_MAIN="net.sf.cb2xml.Cb2Xml" \
    PROLEAP_CLASSPATH="/opt/proleap/lib/*" \
    PROLEAP_MAIN="org.proleap.cobol.tool.CobolParserCLI"

# python deps
RUN pip install --no-cache-dir \
    orjson==3.* jsonschema==4.* chardet==5.* pydantic==2.* uvloop==0.19.* click==8.*

# app files
COPY pyproject.toml ./pyproject.toml
COPY README.md ./README.md
COPY src ./src
COPY schemas ./schemas

# non-root
RUN useradd -m -u 10001 appuser
USER appuser

# runtime env
ENV LOG_LEVEL="info" \
    COBOL_DIALECT="COBOL85" \
    COBOL_COPY_PATH="" \
    ENCODING_HINTS="[]" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/opt/renova/tools/cobol-parser:${PYTHONPATH}"

ENTRYPOINT ["/usr/bin/tini","--","python","-m","src.main"]
CMD ["--stdio"]
