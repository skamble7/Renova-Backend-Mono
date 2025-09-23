# services/learning-service/Dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# --- Install Docker CLI (talks to host daemon via the mounted /var/run/docker.sock)
# Use the official Docker apt repo to ensure /usr/bin/docker exists on bookworm-slim.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gnupg; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc; \
    chmod a+r /etc/apt/keyrings/docker.asc; \
    . /etc/os-release; \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends docker-ce-cli; \
    rm -rf /var/lib/apt/lists/*

# 1) Install shared libs (editable)
COPY libs/pyproject.toml /tmp/libs/pyproject.toml
COPY libs /tmp/libs/libs
RUN pip install -e /tmp/libs

# (optional) sanity check
RUN python - <<'PY'
import importlib
m = importlib.import_module("libs.renova_common.events")
print("OK:", m.__file__)
PY

# 2) Install service deps (no source yet -> better layer reuse)
COPY services/learning-service/pyproject.toml /app/pyproject.toml
RUN pip install .

# 3) Copy the service code
COPY services/learning-service/app /app/app

# 4) Runtime
EXPOSE 9013
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9013"]
