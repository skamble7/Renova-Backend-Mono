# integrations/mcp/cobol/cobol-parser-mcp/Dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-21-jre-headless tini ca-certificates bash \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/renova/tools/cobol-parser

ENV PROLEAP_JAR="/opt/proleap/cb2xml.jar"

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

ENV LOG_LEVEL="info" \
    COBOL_DIALECT="COBOL85" \
    COBOL_COPY_PATH="" \
    ENCODING_HINTS="[]" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/opt/renova/tools/cobol-parser:${PYTHONPATH}"

# Run stdio server directly (line-delimited JSON)
ENTRYPOINT ["/usr/bin/tini","--","python","-m","src.main"]
CMD ["--stdio"]
