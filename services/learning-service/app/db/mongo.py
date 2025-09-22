from __future__ import annotations

import os
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase

# Singleton client for the service process
_client: Optional[AsyncIOMotorClient] = None


def get_client() -> AsyncIOMotorClient:
    """
    Lazily create a global Motor client.
    Uses UUID representation 'standard' for predictable behavior if UUIDs are stored.
    """
    global _client
    if _client is None:
        uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
        _client = AsyncIOMotorClient(uri, uuidRepresentation="standard")
    return _client


def get_db() -> AsyncIOMotorDatabase:
    """
    Returns the configured database.
    """
    db_name = os.getenv("MONGO_DB", "renova")
    return get_client()[db_name]


def get_collection(name: str) -> AsyncIOMotorCollection:
    """
    Convenience accessor for a named collection.
    """
    return get_db()[name]


async def init_db() -> None:
    """
    Hook to invoke on application startup (e.g., FastAPI lifespan).
    Creates indexes used by the learning-service.
    """
    col = get_collection("learning_runs")

    # Idempotent index creation
    await col.create_index("run_id", unique=True, name="uniq_run_id")
    await col.create_index("workspace_id", name="idx_workspace")
    await col.create_index("status", name="idx_status")
    await col.create_index([("workspace_id", 1), ("created_at", -1)], name="idx_workspace_created_desc")
    await col.create_index("pack_id", name="idx_pack_id")
    await col.create_index([("pack_id", 1), ("playbook_id", 1)], name="idx_pack_playbook")


async def close_db() -> None:
    """
    Optional shutdown hook.
    """
    global _client
    if _client is not None:
        _client.close()
        _client = None
