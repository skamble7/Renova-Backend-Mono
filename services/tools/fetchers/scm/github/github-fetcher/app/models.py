# services/tools/fetchers/scm/github/github-fetcher/app/models.py
from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional

class FetchRequest(BaseModel):
    repo_url: HttpUrl = Field(..., description="GitHub HTTPS URL")
    ref: Optional[str] = Field(default="main", description="Branch, tag, or commit")
    workspace: str = Field(..., description="Workspace identifier (used as landing zone folder)")

class FileArtifact(BaseModel):
    path: str
    size: int
    sha1: str

class FetchResponse(BaseModel):
    repository: str
    ref: str
    manifest: List[str]
    files: List[FileArtifact]
