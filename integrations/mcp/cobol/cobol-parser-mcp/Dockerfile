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
      orjson==3.* jsonschema==4.* chardet==5.* pydantic==2.* && \
    pip install --no-cache-dir .

# entrypoint prints readiness to STDOUT then starts the stdio server
RUN printf '%s\n' '#!/usr/bin/env sh' \
                 'set -e' \
                 'echo "mcp server ready"' \
                 'exec python -m cobol_parser_mcp --stdio' > /usr/local/bin/entrypoint.sh \
 && chmod +x /usr/local/bin/entrypoint.sh

ENV CB2XML_CLASSPATH=/opt/cb2xml/lib/* \
    CB2XML_MAIN=net.sf.cb2xml.Cb2Xml \
    PROLEAP_CLASSPATH=/opt/proleap/lib/proleap-cli-bridge.jar \
    PROLEAP_MAIN=com.renova.proleap.CLI

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
