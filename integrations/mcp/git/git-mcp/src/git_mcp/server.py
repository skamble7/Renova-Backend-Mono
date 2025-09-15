from __future__ import annotations

import argparse
import json
from importlib.metadata import version as pkg_version, PackageNotFoundError
from pathlib import Path

from .config import Config
from .mcp import MCPServer, ToolSpec
from .tools import clone_repo as t_clone
from .tools import ls_tree as t_ls
from .tools import read_file as t_read
from .tools import stat_file as t_stat
from .tools import resolve_ref as t_resolve


def _load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_server(cfg: Config) -> MCPServer:
    try:
        ver = pkg_version("git-mcp")
    except PackageNotFoundError:
        ver = "0.0.0"

    srv = MCPServer(server_name="git-mcp", server_version=ver)

    # Register tools
    srv.register(ToolSpec(
        name="clone_repo",
        title="Clone Repository",
        description="Clone a repository into a controlled workspace path and return cam.asset.repo_snapshot",
        input_schema=t_clone.INPUT_SCHEMA,
        output_schema=_load_json(Path(__file__).parent / "schemas" / "tool.clone_repo.output.schema.json"),
        handler=t_clone.make_handler(cfg),
    ))
    srv.register(ToolSpec(
        name="ls_tree",
        title="List Files",
        description="List files at a root with optional globs",
        input_schema=t_ls.INPUT_SCHEMA,
        output_schema=t_ls.OUTPUT_SCHEMA,
        handler=t_ls.make_handler(cfg),
    ))
    srv.register(ToolSpec(
        name="read_file",
        title="Read File",
        description="Read file content with size cap and encoding",
        input_schema=t_read.INPUT_SCHEMA,
        output_schema=None,
        handler=t_read.make_handler(cfg),
    ))
    srv.register(ToolSpec(
        name="stat_file",
        title="Stat File",
        description="Get file metadata and hashes",
        input_schema=t_stat.INPUT_SCHEMA,
        output_schema=t_stat.OUTPUT_SCHEMA,
        handler=t_stat.make_handler(cfg),
    ))
    srv.register(ToolSpec(
        name="resolve_ref",
        title="Resolve Ref",
        description="Resolve a ref to a full commit SHA",
        input_schema=t_resolve.INPUT_SCHEMA,
        output_schema=t_resolve.OUTPUT_SCHEMA,
        handler=t_resolve.make_handler(cfg),
    ))
    return srv


def main() -> None:
    parser = argparse.ArgumentParser(description="git-mcp stdio server")
    parser.add_argument("--stdio", action="store_true", help="Run over stdio (default)")
    args = parser.parse_args()

    cfg = Config.load()
    Path(cfg.work_root).mkdir(parents=True, exist_ok=True)
    Path(cfg.cache_root).mkdir(parents=True, exist_ok=True)

    server = build_server(cfg)
    server.run_stdio()


if __name__ == "__main__":
    main()
