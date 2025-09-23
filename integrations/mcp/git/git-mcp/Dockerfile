FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# git + CA certs
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# app files
WORKDIR /opt/renova/tools/git
COPY pyproject.toml README.md ./
COPY src/ ./src/

# install package (must provide a console_script called `git-mcp`)
RUN pip install --no-cache-dir .

# tiny entrypoint that prints readiness to STDOUT then execs the server
# (the client watches stdout for readiness and then JSON-RPC)
RUN printf '%s\n' '#!/usr/bin/env sh' \
                 'set -e' \
                 'echo "mcp server ready"' \
                 'exec git-mcp "$@"' > /usr/local/bin/entrypoint.sh \
 && chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["--stdio"]
