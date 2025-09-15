# git-mcp (stdio)

Minimal MCP server over stdio exposing deterministic Git tools:

- `clone_repo` → returns `cam.asset.repo_snapshot` (1.0.0)
- `ls_tree` → file inventory (relpath, size, sha256)
- `read_file` → safe, bounded reads
- `stat_file` → metadata + hashes
- `resolve_ref` → resolve SHA from a ref

The server prints **"mcp server ready"** to **stderr** on init.

## Env
- `LOG_LEVEL`             (info|debug|error) default: info
- `REPO_WORK_ROOT`        absolute path for worktrees/clones (default: /mnt/src)
- `REPO_CACHE`            bare cache path (default: /var/cache/git-bare)
- `GIT_ALLOWED_HOSTS`     comma-separated allowlist (optional)
- `GIT_HTTP_TOKEN`        PAT for https (optional)
- `GIT_SSH_KEY`           path to private key (optional)
- `GIT_KNOWN_HOSTS`       path to known_hosts (optional)

## Run
```bash
git-mcp --stdio
