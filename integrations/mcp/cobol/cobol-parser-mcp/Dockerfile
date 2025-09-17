# integrations/mcp/cobol/cobol-parser-mcp/Dockerfile
FROM python:3.12-slim

# ---- System deps (JRE for ProLeap/cb2xml) + tini for clean PID 1
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-21-jre-headless \
    tini \
    ca-certificates \
    bash \
 && rm -rf /var/lib/apt/lists/*

# ---- App layout (keep stable for PYTHONPATH & working dir)
WORKDIR /opt/renova/tools/cobol-parser

# ---- Bake ProLeap/cb2xml jar into the image
# Place your jar at: integrations/mcp/cobol/cobol-parser-mcp/vendor/cb2xml.jar
# (This path is relative to your repo root when building the image below.)
RUN mkdir -p /opt/proleap
COPY vendor/cb2xml.jar /opt/proleap/cb2xml.jar
# Make sure the non-root user can read it
RUN chmod 0644 /opt/proleap/cb2xml.jar

# Tell the adapter where the JAR lives
ENV PROLEAP_JAR="/opt/proleap/cb2xml.jar"

# ---- Python deps (pin the minimal set you listed)
RUN pip install --no-cache-dir \
    orjson==3.* \
    jsonschema==4.* \
    chardet==5.* \
    pydantic==2.* \
    uvloop==0.19.* \
    click==8.*

# ---- App files
COPY pyproject.toml ./pyproject.toml
COPY README.md ./README.md
COPY src ./src
COPY schemas ./schemas

# ---- Non-root
RUN useradd -m -u 10001 appuser
USER appuser

# ---- Runtime env
ENV LOG_LEVEL="info" \
    COBOL_DIALECT="COBOL85" \
    COBOL_COPY_PATH="" \
    ENCODING_HINTS="[]" \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/opt/renova/tools/cobol-parser:${PYTHONPATH}"

# ---- Start the stdio JSON-RPC server (tini = clean signals)
ENTRYPOINT ["/usr/bin/tini","--","python","-m","src.main"]
CMD ["--stdio"]
