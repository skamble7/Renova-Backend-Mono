# services/capability-service/app/middleware/logging.py
from __future__ import annotations
import time
import logging
from fastapi import FastAPI, Request

logger = logging.getLogger("app.middleware")


def install_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def _log_requests(request: Request, call_next):
        start = time.time()
        path = request.url.path
        method = request.method
        try:
            response = await call_next(request)
            duration = (time.time() - start) * 1000.0
            logger.info("%s %s -> %s (%.2f ms)", method, path, response.status_code, duration)
            return response
        except Exception as ex:
            duration = (time.time() - start) * 1000.0
            logger.exception("Unhandled error during %s %s (%.2f ms): %s", method, path, duration, ex)
            raise
