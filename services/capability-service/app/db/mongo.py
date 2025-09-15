from __future__ import annotations

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import settings

_client: Optional[AsyncIOMotorClient] = None


def get_client() -> AsyncIOMotorClient:
    """
    Lazily create (and reuse) the Motor client.
    """
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri)
    return _client


def get_db() -> AsyncIOMotorDatabase:
    """
    Return the database handle using configured DB name.
    """
    return get_client()[settings.mongo_db]


async def init_indexes() -> None:
    """
    Create indexes for all capability-service collections.
    Call this from FastAPI startup.
    """
    db = get_db()

    # capabilities
    await db.capabilities.create_index("id", unique=True)
    await db.capabilities.create_index("tags")
    await db.capabilities.create_index("produces_kinds")

    # integrations
    await db.integrations.create_index("id", unique=True)
    await db.integrations.create_index("name")
    await db.integrations.create_index("transport.kind")  # <- new
    await db.integrations.create_index("tags")

    # capability_packs
    await db.capability_packs.create_index([("key", 1), ("version", 1)], unique=True)
    await db.capability_packs.create_index("status")
    # optional text index for title/description search
    try:
        await db.capability_packs.create_index([("title", "text"), ("description", "text")])
    except Exception:
        # Some Mongo tiers disallow text index duplicates; ignore if it already exists.
        pass
