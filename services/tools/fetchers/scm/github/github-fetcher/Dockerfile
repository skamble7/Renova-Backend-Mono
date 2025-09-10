# services/tools/fetchers/scm/github/github-fetcher/Dockerfile
FROM python:3.12-slim

# Install git + ssh + CA certs (+ curl for healthcheck)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      git openssh-client ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Make sure GitPython stays quiet if it has to refresh, and explicitly point it to git
ENV GIT_PYTHON_REFRESH=quiet
ENV GIT_PYTHON_GIT_EXECUTABLE=/usr/bin/git
# Optional: enforce ssh config to avoid host key prompts in CI
ENV GIT_SSH_COMMAND="ssh -o StrictHostKeyChecking=accept-new"

# Create app user & dirs
WORKDIR /app
RUN useradd -m -u 10001 appuser && mkdir -p /app && chown -R appuser:appuser /app

# Copy and install deps first (better layer caching)
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app
COPY ./app /app/app
RUN chown -R appuser:appuser /app

# Landing zone mount point (compose provides the volume)
RUN mkdir -p /landing_zone && chown -R appuser:appuser /landing_zone
ENV LANDING_ZONE=/landing_zone

USER appuser

EXPOSE 8080
# Use curl in healthcheck; uvicorn is the entrypoint
HEALTHCHECK --interval=15s --timeout=5s --retries=10 CMD curl -fsS http://localhost:8080/docs || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
