# integrations/mcp/git/git-mcp/src/git_mcp/config.py
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Optional, Set

@dataclass(frozen=True)
class Config:
    log_level: str
    work_root: str
    cache_root: str
    allowed_hosts: Optional[Set[str]]
    git_http_token: Optional[str]
    git_ssh_key: Optional[str]
    git_known_hosts: Optional[str]
    disable_reference: bool                      # <— NEW

    @staticmethod
    def load() -> "Config":
        allowed_env = os.getenv("GIT_ALLOWED_HOSTS")
        allowed_hosts = (
            {h.strip() for h in allowed_env.split(",") if h.strip()}
            if allowed_env else None
        )
        return Config(
            log_level=os.getenv("LOG_LEVEL", "info").lower(),
            work_root=os.getenv("REPO_WORK_ROOT", "/mnt/src"),
            cache_root=os.getenv("REPO_CACHE", "/var/cache/git-bare"),
            allowed_hosts=allowed_hosts,
            git_http_token=os.getenv("GIT_HTTP_TOKEN"),
            git_ssh_key=os.getenv("GIT_SSH_KEY"),
            git_known_hosts=os.getenv("GIT_KNOWN_HOSTS"),
            disable_reference=os.getenv("GIT_DISABLE_REFERENCE", "0") in ("1", "true", "yes"),
        )
