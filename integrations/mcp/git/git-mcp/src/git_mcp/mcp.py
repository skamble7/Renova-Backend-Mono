# integrations/mcp/git/git-mcp/src/git_mcp/mcp.py
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from jsonschema import validate, ValidationError


@dataclass
class ToolSpec:
    name: str
    title: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]]
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]


class MCPServer:
    """
    Minimal MCP over JSON-RPC via stdio:
    - initialize / notifications/initialized / shutdown (no-op) / exit (no-op)
    - tools/list, tools/call
    """

    def __init__(self, server_name: str = "git-mcp", server_version: str = "0.0.0") -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._server_name = server_name
        self._server_version = server_version
        # Advertise only the features we actually implement.
        self._capabilities = {
            "tools": {}  # we support tools/list and tools/call
            # You could add: "prompts": {}, "resources": {}, etc. when implemented
        }

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    # ---- low-level io ----
    def _send(self, obj: Dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
        sys.stdout.flush()

    def _send_error(self, id_val: Any, code: int, message: str, data: Optional[Dict[str, Any]] = None) -> None:
        self._send({
            "jsonrpc": "2.0",
            "id": id_val,
            "error": {"code": code, "message": message, "data": data or {}}
        })

    # ---- protocol handlers ----
    def _handle_initialize(self, msg: Dict[str, Any]) -> None:
        # Accept any params; return server info + capabilities.
        result = {
            # Spec allows a freeform version string; clients generally just check it's present.
            "protocolVersion": "0.1",
            "serverInfo": {"name": self._server_name, "version": self._server_version},
            "capabilities": self._capabilities,
        }
        self._send({"jsonrpc": "2.0", "id": msg.get("id"), "result": result})

    def _handle_initialized_notification(self, _msg: Dict[str, Any]) -> None:
        # No response for notifications/initialized
        return

    def _handle_shutdown(self, msg: Dict[str, Any]) -> None:
        # LSP-style courtesy; return null result.
        self._send({"jsonrpc": "2.0", "id": msg.get("id"), "result": None})

    def _handle_tools_list(self, msg: Dict[str, Any]) -> None:
        result = {
            "tools": [
                {
                    "name": t.name,
                    "title": t.title,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                    **({"outputSchema": t.output_schema} if t.output_schema else {})
                }
                for t in self._tools.values()
            ]
        }
        self._send({"jsonrpc": "2.0", "id": msg.get("id"), "result": result})

    def _handle_tools_call(self, msg: Dict[str, Any]) -> None:
        params = msg.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}

        if not name or name not in self._tools:
            self._send_error(msg.get("id"), -32601, f"Unknown tool: {name}")
            return

        spec = self._tools[name]
        try:
            validate(instance=args, schema=spec.input_schema)
        except ValidationError as ve:
            self._send_error(msg.get("id"), -32602, "Invalid params", {"detail": ve.message})
            return

        try:
            out = spec.handler(args)
        except Exception as ex:  # noqa
            self._send({
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "result": {
                    "content": [{"type": "text", "text": str(ex)}],
                    "isError": True
                }
            })
            return

        if spec.output_schema:
            try:
                structured = out.get("structuredContent")
                if structured is not None:
                    validate(instance=structured, schema=spec.output_schema)
            except ValidationError as ve:
                self._send({
                    "jsonrpc": "2.0",
                    "id": msg.get("id"),
                    "result": {
                        "content": [{"type": "text", "text": f"Output schema validation failed: {ve.message}"}],
                        "isError": True
                    }
                })
                return

        self._send({"jsonrpc": "2.0", "id": msg.get("id"), "result": out})

    # ---- main loop ----
    def run_stdio(self) -> None:
        print("mcp server ready", file=sys.stderr, flush=True)
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue

            method = msg.get("method")
            if method == "initialize":
                self._handle_initialize(msg)
            elif method == "notifications/initialized":
                self._handle_initialized_notification(msg)
            elif method == "shutdown":
                self._handle_shutdown(msg)
            elif method == "tools/list":
                self._handle_tools_list(msg)
            elif method == "tools/call":
                self._handle_tools_call(msg)
            elif method == "exit":
                # polite no-op; caller controls process lifetime
                break
            else:
                self._send_error(msg.get("id"), -32601, f"Unknown method: {method}")
