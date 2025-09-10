# services/artifact-service/app/routers/__init__.py
from __future__ import annotations

from fastapi import APIRouter

from .registry_routes import router as registry_router
from .artifact_routes import router as artifacts_router

router = APIRouter()
router.include_router(registry_router)
router.include_router(artifacts_router)
