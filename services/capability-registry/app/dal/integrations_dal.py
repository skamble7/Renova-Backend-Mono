from __future__ import annotations
import datetime as dt
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, TEXT
from pymongo.errors import OperationFailure
from ..models.integrations import (
    Connector, ConnectorCreate, ConnectorUpdate,
    ToolSpec, ToolCreate, ToolUpdate
)

CONNECTORS = "integrations_connectors"
TOOLS = "integrations_tools"

async def ensure_indexes(db: AsyncIOMotorDatabase):
    c = db[CONNECTORS]; t = db[TOOLS]
    await c.create_index([("key", ASCENDING)], name="uniq_key", unique=True)
    await c.create_index([("type", ASCENDING), ("vendor", ASCENDING)], name="type_vendor")
    await t.create_index([("key", ASCENDING)], name="uniq_key", unique=True)
    await t.create_index([("connector_key", ASCENDING)], name="fk_connector")
    await t.create_index([("produces_kinds", ASCENDING)], name="produces_kinds")
    # NEW:
    await t.create_index([("requires_kinds", ASCENDING)], name="requires_kinds")


# Connectors
async def create_connector(db: AsyncIOMotorDatabase, body: ConnectorCreate) -> Connector:
    now = dt.datetime.utcnow()
    doc = {**body.model_dump(), "created_at": now, "updated_at": now}
    await db[CONNECTORS].insert_one(doc)
    return Connector(**doc)

async def get_connector(db: AsyncIOMotorDatabase, key: str) -> Optional[Connector]:
    d = await db[CONNECTORS].find_one({"key": key}, projection={"_id": False})
    return Connector(**d) if d else None

async def list_connectors(db: AsyncIOMotorDatabase) -> List[Dict[str, Any]]:
    cur = db[CONNECTORS].find({}, projection={"_id": False}).sort([("key", 1)])
    return [d async for d in cur]

async def update_connector(db: AsyncIOMotorDatabase, key: str, patch: ConnectorUpdate) -> Optional[Connector]:
    upd = {k:v for k,v in patch.model_dump(exclude_none=True).items()}
    upd["updated_at"] = dt.datetime.utcnow()
    d = await db[CONNECTORS].find_one_and_update({"key": key}, {"$set": upd}, return_document=True, projection={"_id": False})
    return Connector(**d) if d else None

async def delete_connector(db: AsyncIOMotorDatabase, key: str) -> bool:
    return (await db[CONNECTORS].delete_one({"key": key})).deleted_count == 1

# Tools
async def create_tool(db: AsyncIOMotorDatabase, body: ToolCreate) -> ToolSpec:
    now = dt.datetime.utcnow()
    doc = {**body.model_dump(), "created_at": now, "updated_at": now}
    await db[TOOLS].insert_one(doc)
    return ToolSpec(**doc)

async def get_tool(db: AsyncIOMotorDatabase, key: str) -> Optional[ToolSpec]:
    d = await db[TOOLS].find_one({"key": key}, projection={"_id": False})
    return ToolSpec(**d) if d else None

async def list_tools(db: AsyncIOMotorDatabase, connector_key: Optional[str] = None) -> List[Dict[str, Any]]:
    q: Dict[str, Any] = {}
    if connector_key:
        q["connector_key"] = connector_key
    cur = db[TOOLS].find(q, projection={"_id": False}).sort([("key", 1)])
    return [d async for d in cur]

async def update_tool(db: AsyncIOMotorDatabase, key: str, patch: ToolUpdate) -> Optional[ToolSpec]:
    upd = {k:v for k,v in patch.model_dump(exclude_none=True).items()}
    upd["updated_at"] = dt.datetime.utcnow()
    d = await db[TOOLS].find_one_and_update({"key": key}, {"$set": upd}, return_document=True, projection={"_id": False})
    return ToolSpec(**d) if d else None

async def delete_tool(db: AsyncIOMotorDatabase, key: str) -> bool:
    return (await db[TOOLS].delete_one({"key": key})).deleted_count == 1
