# services/tools/fetchers/scm/github/github-fetcher/app/services/git_service.py
from __future__ import annotations

import os
import shutil
import logging
import re
from pathlib import Path
from typing import Iterable, List, Optional, Any

import git  # GitPython

from ..utils.file_utils import sha1_of_file
from ..models import FileArtifact

logger = logging.getLogger(__name__)

# --- Ensure Git CLI is available for GitPython (prevents "Bad git executable") ---
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")
_GIT_PATH = os.environ.get("GIT_PYTHON_GIT_EXECUTABLE") or shutil.which("git")
if not _GIT_PATH:
    raise RuntimeError(
        "git CLI not found. Install git in the image and/or set GIT_PYTHON_GIT_EXECUTABLE."
    )
try:
    git.Git.refresh(path=_GIT_PATH)  # hint GitPython explicitly
except Exception as e:
    raise RuntimeError(f"Failed to initialize GitPython with git at '{_GIT_PATH}': {e}")


def _as_str(v: Any) -> str:
    """Best-effort safe string conversion (handles Pydantic Url, None, etc.)."""
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        # Last resort
        return f"{v}"


def _sanitize_remote(url: Any) -> str:
    """Remove embedded credentials from a URL for logging (robust to non-str inputs)."""
    s = _as_str(url)
    # mask things like https://user:pass@host/...
    return re.sub(r"://[^/@:]+@", "://***@", s)


def _maybe_inject_token(url: Any, token: Optional[str]) -> str:
    """
    If an HTTPS token is provided, inject it into the URL for the clone operation only.
    Token is later removed from the configured remote to avoid persistence.
    """
    s = _as_str(url)
    if not token:
        return s
    if s.startswith("https://"):
        # Minimal form accepted by git: https://<token>@host/org/repo.git
        return s.replace("https://", f"https://{token}@")
    return s


class GitService:
    """
    Workspace layout:
      /landing_zone/
        <workspace>/
          repo/        ← full repo checkout here
    """

    def __init__(self, base_dir: str = "/landing_zone"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def fetch_repo(
        self,
        repo_url: str | Any,
        ref: str,
        workspace: str,
        *,
        depth: int = 1,
        single_branch: bool = True,
        fetch_submodules: bool = False,
        github_token: Optional[str] = None,
    ):
        """
        Clone/checkout the repository into the workspace and return a manifest + file metadata.
        """
        ws_path = self.base_dir / workspace
        repo_path = ws_path / "repo"

        # Clean workspace/repo directory
        if repo_path.exists():
            shutil.rmtree(repo_path)
        ws_path.mkdir(parents=True, exist_ok=True)

        repo_url_str = _as_str(repo_url)
        token = github_token or os.getenv("GITHUB_TOKEN")
        url_for_clone = _maybe_inject_token(repo_url_str, token)

        logger.info(
            "Cloning repo",
            extra={
                "repo": _sanitize_remote(repo_url_str),
                "workspace": workspace,
                "depth": depth,
                "single_branch": single_branch,
            },
        )

        # Perform a shallow clone
        try:
            repo = git.Repo.clone_from(
                url_for_clone,
                repo_path,
                depth=depth if depth and depth > 0 else None,
                single_branch=single_branch,
                no_single_branch=not single_branch,
            )
        except Exception as e:
            msg = f"Clone failed for { _sanitize_remote(repo_url_str) }: {e}"
            logger.error(msg)
            raise

        # Immediately sanitize origin URL if we injected a token
        try:
            if url_for_clone != repo_url_str:
                repo.remotes.origin.set_url(repo_url_str)
        except Exception:
            pass

        # Ensure ref exists locally; fetch if necessary
        if ref:
            try:
                self._safe_checkout(repo, ref)
            except Exception:
                try:
                    repo.git.fetch("origin", ref, depth=depth if depth and depth > 0 else None)
                    self._safe_checkout(repo, ref)
                except Exception:
                    repo.git.fetch("--all", "--tags", *(["--depth", str(depth)] if depth and depth > 0 else []))
                    self._safe_checkout(repo, ref)
        else:
            ref = repo.head.commit.hexsha

        # Submodules (optional)
        if fetch_submodules and (repo_path / ".gitmodules").exists():
            try:
                repo.git.submodule("update", "--init", "--recursive", *(["--depth", str(depth)] if depth and depth > 0 else []))
            except Exception as e:
                logger.warning(f"Submodule update failed: {e}")

        # Build artifacts list (exclude .git/)
        files: List[FileArtifact] = []
        for path in self._iter_files(repo_path):
            rel = path.relative_to(ws_path)
            files.append(
                FileArtifact(
                    path=str(rel),
                    size=path.stat().st_size,
                    sha1=sha1_of_file(path),
                )
            )

        manifest = [f.path for f in files]

        return {
            "repository": _sanitize_remote(repo_url_str),
            "ref": str(ref),
            "manifest": manifest,
            "files": files,
        }

    # ───────────────────────── Helpers ─────────────────────────

    def _iter_files(self, root: Path) -> Iterable[Path]:
        git_dir = (root / ".git").resolve()
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    if git_dir in p.resolve().parents:
                        continue
                except Exception:
                    pass
                yield p

    def _safe_checkout(self, repo: git.Repo, ref: str) -> None:
        """Checkout ref that may be a branch, tag, or commit SHA."""
        try:
            repo.git.checkout(ref)
            return
        except Exception:
            pass
        try:
            repo.git.checkout(f"origin/{ref}")
            return
        except Exception:
            pass
        try:
            repo.git.checkout(f"tags/{ref}")
            return
        except Exception:
            pass
        try:
            repo.git.checkout(ref, "--force")
            return
        except Exception as e:
            raise RuntimeError(f"Unable to checkout ref '{ref}': {e}")
