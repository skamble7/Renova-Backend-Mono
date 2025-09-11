# services/tools/fetchers/scm/github/github-fetcher/app/main.py
from __future__ import annotations

import logging
from fastapi import FastAPI, HTTPException
from .models import FetchRequest, FetchResponse
from .services.git_service import GitService, _as_str

logger = logging.getLogger(__name__)

app = FastAPI(title="GitHub Fetcher", version="1.0.0")

git_service = GitService(base_dir="/landing_zone")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/fetch", response_model=FetchResponse)
def fetch_code(req: FetchRequest):
    try:
        # Pydantic v2's HttpUrl is a Url object — convert to str before passing on.
        result = git_service.fetch_repo(_as_str(req.repo_url), req.ref or "main", req.workspace)
        return FetchResponse(**result)
    except Exception as e:
        logger.exception("fetch.failed")
        # Ensure everything in detail is JSON-serializable
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "repo_url": _as_str(req.repo_url),
                "workspace": req.workspace,
            },
        )
