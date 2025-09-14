# services/capability-service/app/main.py
from __future__ import annotations

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.logging_conf import setup_logging
from app.middleware import add_cors, install_request_logging, add_error_handlers
from app.db.mongo import init_indexes
from app.events import get_bus
from app.routers import (
    capability_router,
    integration_router,
    pack_router,
    resolved_router,
    health_router,
)
from app.seeds import run_all_seeds  # ← idempotent seed runner

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Logging first
    setup_logging()
    logger.info("Starting %s on %s:%s", settings.app_name, settings.host, settings.port)

    # Initialize Mongo indexes
    try:
        await init_indexes()
        logger.info("Mongo indexes initialized")
    except Exception as e:
        logger.exception("Failed to initialize Mongo indexes: %s", e)
        # Let the service start; routers may still function if collections exist.

    # Connect RabbitMQ (non-fatal if broker is temporarily unavailable)
    try:
        await get_bus().connect()
    except Exception as e:
        logger.warning("RabbitMQ connect failed (will continue without bus): %s", e)

    # Run seeds (idempotent; controlled by env flags)
    try:
        await run_all_seeds()
        logger.info("Seed routines completed (or skipped)")
    except Exception as e:
        logger.warning("Seeding failed: %s", e)

    yield

    # Shutdown
    try:
        await get_bus().close()
    except Exception:
        pass
    logger.info("Shutdown complete")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Middlewares
add_cors(app)
install_request_logging(app)
add_error_handlers(app)

# Routers
app.include_router(health_router)
app.include_router(capability_router)
app.include_router(integration_router)
app.include_router(pack_router)
app.include_router(resolved_router)


@app.get("/")
async def root():
    return {
        "service": settings.service_name,
        "name": settings.app_name,
        "status": "ok",
        "docs": "/docs",
        "openapi": "/openapi.json",
    }


if __name__ == "__main__":
    import uvicorn

    reload_flag = os.getenv("RELOAD", "0") in ("1", "true", "True")
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=reload_flag,
        log_level="info",
    )
