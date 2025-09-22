FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 1) Install shared libs (editable) — mirrors your other services
#    If your mono-repo has a "libs" workspace, this keeps versions aligned.
COPY libs/pyproject.toml /tmp/libs/pyproject.toml
COPY libs /tmp/libs/libs
RUN pip install --no-cache-dir -e /tmp/libs

# (optional) sanity check that shared libs import fine
RUN python - <<'PY'
import importlib
try:
    m = importlib.import_module("libs.renova_common.events")
    print("OK:", m.__file__)
except Exception as e:
    print("Shared libs not present or import failed:", e)
PY

# 2) Install service deps from this service's pyproject
COPY services/learning-service/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir .

# 3) Copy the service code
COPY services/learning-service/app /app/app

# 4) Runtime (Internal port 9013 by convention; adjust via env)
EXPOSE 9013
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9013"]
