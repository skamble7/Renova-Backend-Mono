from fastapi import FastAPI, HTTPException
from .models import FetchRequest, FetchResponse
from .services.git_service import GitService

app = FastAPI(title="GitHub Fetcher", version="1.0.0")

git_service = GitService(base_dir="/landing_zone")

@app.post("/fetch", response_model=FetchResponse)
def fetch_code(req: FetchRequest):
    try:
        result = git_service.fetch_repo(req.repo_url, req.ref, req.workspace)
        return FetchResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
