from __future__ import annotations
import contextvars
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from starlette.requests import Request

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        cid = request.headers.get("x-correlation-id") or rid
        token_r = request_id_var.set(rid)
        token_c = correlation_id_var.set(cid)
        try:
            response = await call_next(request)
            response.headers["x-request-id"] = rid
            response.headers["x-correlation-id"] = cid
            return response
        finally:
            request_id_var.reset(token_r)
            correlation_id_var.reset(token_c)

class CorrelationIdFilter:
    def filter(self, record):
        try:
            rid = request_id_var.get()
            cid = correlation_id_var.get()
            if rid:
                record.request_id = rid
            if cid:
                record.correlation_id = cid
        except Exception:
            pass
        return True
