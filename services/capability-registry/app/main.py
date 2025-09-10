# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from .logging_conf import configure_logging
from .routers.capability_routes import router as capability_router
from .routers.integrations_routes import router as integrations_router
from .routers.resolve_routes import router as resolve_router
from .db.mongodb import get_db
from .dal.capability_dal import ensure_indexes as ensure_cap_indexes
from .dal.integrations_dal import ensure_indexes as ensure_integ_indexes
from .seeds.capabilities_seed import run_capabilities_seed
from .seeds.integrations_seed import run_integrations_seed   # ← new
from .config import settings
from .middleware.correlation import CorrelationIdMiddleware, CorrelationIdFilter

configure_logging()
app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
    expose_headers=["x-request-id","x-correlation-id"],
)
app.add_middleware(CorrelationIdMiddleware)

_corr = CorrelationIdFilter()
for n in ("", "uvicorn.access", "uvicorn.error", "app"):
    logging.getLogger(n).addFilter(_corr)

@app.get("/health")
async def health():
    db = await get_db(); await db.command("ping"); return {"status": "ok"}

@app.on_event("startup")
async def on_startup():
    db = await get_db()
    await ensure_cap_indexes(db)
    await ensure_integ_indexes(db)
    await run_capabilities_seed(db)
    await run_integrations_seed(db)     # optional seed for connectors/tools

app.include_router(capability_router)
app.include_router(integrations_router)
app.include_router(resolve_router)
