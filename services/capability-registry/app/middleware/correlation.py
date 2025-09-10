# app/middleware/correlation.py
import uuid, logging
import contextvars
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

request_id_var = contextvars.ContextVar("request_id", default=None)
correlation_id_var = contextvars.ContextVar("correlation_id", default=None)

class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.correlation_id = correlation_id_var.get()
        return True

class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        corr_id = request.headers.get("x-correlation-id") or req_id
        request_id_var.set(req_id)
        correlation_id_var.set(corr_id)
        response = await call_next(request)
        response.headers["x-request-id"] = req_id
        response.headers["x-correlation-id"] = corr_id
        return response
