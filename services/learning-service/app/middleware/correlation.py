from __future__ import annotations

import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response


HEADER_NAME = "X-Correlation-ID"
STATE_ATTR = "correlation_id"


def get_correlation_id(request: Request) -> str:
    """
    Accessor for handlers to read the correlation id.
    """
    return getattr(request.state, STATE_ATTR, "")


def add_correlation_middleware(app: FastAPI) -> None:
    """
    Registers a lightweight middleware that ensures every request/response
    carries an X-Correlation-ID. If absent, a new one is generated.
    """

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next: Callable):
        corr = request.headers.get(HEADER_NAME) or uuid.uuid4().hex
        setattr(request.state, STATE_ATTR, corr)

        response: Response = await call_next(request)
        if HEADER_NAME not in response.headers:
            response.headers[HEADER_NAME] = corr
        return response
