from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.logging import configure_logging
from app.middleware.correlation import add_correlation_middleware
from app.db.mongo import init_db, close_db
from app.infra.rabbit import get_bus

# Routers
from app.routers.health import router as health_router
from app.routers.packs import router as packs_router
from app.routers.runs import router as runs_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_logging()
    logger = logging.getLogger("app.main")
    logger.info("learning-service starting up")
    await init_db()
    try:
        await get_bus().connect()
    except Exception as e:
        # Non-fatal if RabbitMQ is down; service can still run
        logger.warning("Rabbit connection failed: %r", e)
    yield
    # Shutdown
    await close_db()
    try:
        await get_bus().close()
    except Exception:
        pass
    logger.info("learning-service shutdown complete")


app = FastAPI(title="Renova Learning Service", lifespan=lifespan)

# Correlation middleware
add_correlation_middleware(app)

# Mount routers
app.include_router(health_router)
app.include_router(packs_router)
app.include_router(runs_router)
