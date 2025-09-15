FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Runtime dirs
RUN mkdir -p /opt/renova/tools/git /var/cache/git-bare /mnt/src
WORKDIR /opt/renova/tools/git

# Install server
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Ensure entrypoint is executable
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV LOG_LEVEL=info \
    REPO_WORK_ROOT=/mnt/src \
    REPO_CACHE=/var/cache/git-bare

# stdout must only carry MCP messages; readiness goes to stderr
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
