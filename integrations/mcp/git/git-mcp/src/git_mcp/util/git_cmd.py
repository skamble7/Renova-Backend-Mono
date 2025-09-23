# integrations/mcp/git/git-mcp/src/git_mcp/util/git_cmd.py
from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from .fs import ensure_under_root


class GitError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Optional[str] = None, extra_env: Optional[dict] = None) -> str:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    try:
        out = subprocess.check_output(cmd, cwd=cwd, env=env, stderr=subprocess.STDOUT, text=True)
        return out.strip()
    except subprocess.CalledProcessError as e:
        raise GitError(f"git failed: {' '.join(map(shlex.quote, cmd))}\n{e.output}") from e


def enforce_allowed_host(url: str, allowed_hosts: Optional[set[str]]) -> None:
    if not allowed_hosts:
        return
    host = urlparse(url).hostname
    if not host or host not in allowed_hosts:
        raise GitError(f"host not allowed: {host}")


def cache_path_for(cache_root: str, url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    return str(Path(cache_root) / f"{digest}.git")


def ensure_cache_updated(cache_root: str, url: str) -> str:
    """
    Maintain a bare cache of the remote for speed & idempotency.
    Auto-heal if the cache looks corrupt.
    """
    cpath = cache_path_for(cache_root, url)
    cdir = Path(cpath)
    cdir.parent.mkdir(parents=True, exist_ok=True)

    def _fresh_clone() -> None:
        _run(["git", "clone", "--bare", "--filter=blob:none", url, cpath])

    if not cdir.exists():
        _fresh_clone()
        return cpath

    try:
        _run(["git", "-C", cpath, "remote", "set-url", "origin", url])
        _run(["git", "-C", cpath, "fetch", "--all", "--prune"])
    except GitError:
        # Blow away and recreate
        for p in sorted(cdir.glob("**/*"), reverse=True):
            try:
                p.unlink()
            except IsADirectoryError:
                pass
            except FileNotFoundError:
                pass
        try:
            cdir.rmdir()
        except Exception:
            pass
        _fresh_clone()
    return cpath


def clone_or_update(
    url: str,
    branch: str,
    dest: str,
    depth: int,
    work_root: str,
    cache_root: str,
    use_reference: bool = True,
) -> Tuple[str, str]:
    """
    Ensure dest is a checkout of `url` at `branch`.
    Returns (commit_sha, dest_path). Falls back to no-reference clone if needed.
    """
    allowed = set(os.getenv("GIT_ALLOWED_HOSTS", "").split(",")) if os.getenv("GIT_ALLOWED_HOSTS") else None
    enforce_allowed_host(url, allowed)

    dest_p = ensure_under_root(work_root, dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)

    cache = None
    if use_reference:
        cache = ensure_cache_updated(cache_root, url)

    def _do_clone(reference_ok: bool) -> None:
        if dest_p.exists() and (dest_p / ".git").exists():
            _run(["git", "-C", str(dest_p), "remote", "set-url", "origin", url])
            _run(["git", "-C", str(dest_p), "fetch", "--all", "--prune"])
            _run(["git", "-C", str(dest_p), "checkout", branch])
            _run(["git", "-C", str(dest_p), "reset", "--hard", f"origin/{branch}"])
            return
        cmd = ["git", "clone", "--origin", "origin", "--branch", branch]
        if depth and depth > 0:
            cmd += ["--depth", str(depth), "--single-branch"]
        if reference_ok and cache:
            cmd += ["--reference-if-able", cache, "--dissociate"]
        cmd += [url, str(dest_p)]
        _run(cmd)

    try:
        _do_clone(reference_ok=use_reference)
    except GitError as e1:
        # Fallback to no-reference clone
        if use_reference:
            # best-effort cleanup of partial dest
            if dest_p.exists():
                for p in sorted(dest_p.glob("**/*"), reverse=True):
                    try:
                        p.unlink()
                    except IsADirectoryError:
                        pass
                    except FileNotFoundError:
                        pass
                try:
                    dest_p.rmdir()
                except Exception:
                    pass
            _do_clone(reference_ok=False)
        else:
            raise e1

    sha = _run(["git", "-C", str(dest_p), "rev-parse", "HEAD"])
    return sha, str(dest_p)


def resolve_ref(root: str, ref: str) -> str:
    """Return a full commit SHA for `ref` (e.g., HEAD, branch, tag)."""
    return _run(["git", "-C", root, "rev-parse", ref])
