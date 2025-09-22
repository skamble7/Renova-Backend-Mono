"""
Thin invocation layer for MCP integrations based on the transport snapshot
delivered by capability-service (within a published Capability Pack).

Exports:
- IntegrationInvoker: chooses the transport (http|stdio) and invokes a tool.
- HTTPTransport, StdioTransport: low-level transports (rarely used directly).
"""
from .invoker import IntegrationInvoker  # noqa: F401
from .transport_http import HTTPTransport  # noqa: F401
from .transport_stdio import StdioTransport  # noqa: F401
