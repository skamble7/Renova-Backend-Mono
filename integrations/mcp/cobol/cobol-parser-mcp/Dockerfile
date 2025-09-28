FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Java runtime for cb2xml/proleap jars
RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-21-jre-headless ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/renova/tools/cobol-parser

# vendor jars
RUN mkdir -p /opt/cb2xml/lib /opt/proleap/lib
COPY vendor/cb2xml/lib/*.jar /opt/cb2xml/lib/
COPY vendor/proleap/lib/*.jar /opt/proleap/lib/

# server code
COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY schemas ./schemas

# install python deps / package
RUN pip install --no-cache-dir \
      orjson==3.* jsonschema==4.* chardet==5.* pydantic==2.* click==8.* \
  && pip install --no-cache-dir .

# simple entrypoint to run the stdio server
RUN printf '%s\n' '#!/usr/bin/env sh' \
                 'set -e' \
                 'exec python -m src.main --stdio' > /usr/local/bin/entrypoint.sh \
 && chmod +x /usr/local/bin/entrypoint.sh

# Sensible defaults; overridable at runtime
ENV CB2XML_CLASSPATH=/opt/cb2xml/lib/* \
    CB2XML_MAIN=net.sf.cb2xml.Cb2Xml \
    PROLEAP_CLASSPATH=/opt/proleap/lib/proleap-cli-bridge.jar \
    PROLEAP_MAIN=com.renova.proleap.CLI \
    WORKSPACE_CONTAINER=/workspace \
    COBOL_JAVA_TIMEOUT_SEC=12 \
    COBOL_PARSER_BUDGET_SECONDS=0 \
    COBOL_SOURCE_FORMAT=FIXED

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
