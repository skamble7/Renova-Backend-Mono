from fastapi import APIRouter, Depends, HTTPException, status, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from ..db.mongodb import get_db
from ..services.artifact_registry_client import ArtifactRegistryClient
from ..dal import integrations_dal as dal
from ..models.integrations import *

router = APIRouter(prefix="/integrations", tags=["integrations"])

@router.get("/connectors", response_model=list[dict])
async def list_connectors(db: AsyncIOMotorDatabase = Depends(get_db)):
    return await dal.list_connectors(db)

@router.post("/connectors", response_model=Connector, status_code=status.HTTP_201_CREATED)
async def create_connector(body: ConnectorCreate, db: AsyncIOMotorDatabase = Depends(get_db)):
    return await dal.create_connector(db, body)

@router.put("/connectors/{key}", response_model=Connector)
async def update_connector(key: str, body: ConnectorUpdate, db: AsyncIOMotorDatabase = Depends(get_db)):
    c = await dal.update_connector(db, key, body)
    if not c: raise HTTPException(404, "Not found")
    return c

@router.delete("/connectors/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connector(key: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    if not await dal.delete_connector(db, key): raise HTTPException(404, "Not found")

@router.get("/tools", response_model=list[dict])
async def list_tools(connector_key: str|None = Query(None), db: AsyncIOMotorDatabase = Depends(get_db)):
    return await dal.list_tools(db, connector_key)

@router.post("/tools", response_model=ToolSpec, status_code=status.HTTP_201_CREATED)
async def create_tool(body: ToolCreate, db: AsyncIOMotorDatabase = Depends(get_db)):
    if not await dal.get_connector(db, body.connector_key):
        raise HTTPException(422, f"Unknown connector_key '{body.connector_key}'")

    kinds = set((body.produces_kinds or [])) | set((body.requires_kinds or []))
    if kinds:
        client = ArtifactRegistryClient()
        valid, invalid = await client.validate_kinds(list(kinds))
        if invalid:
            raise HTTPException(422, {"invalid": invalid, "valid": valid})
    return await dal.create_tool(db, body)


@router.put("/tools/{key}", response_model=ToolSpec)
async def update_tool(key: str, body: ToolUpdate, db: AsyncIOMotorDatabase = Depends(get_db)):
    kinds = set(body.produces_kinds or []) | set(body.requires_kinds or [])
    if kinds:
        client = ArtifactRegistryClient()
        valid, invalid = await client.validate_kinds(list(kinds))
        if invalid:
            raise HTTPException(422, {"invalid": invalid, "valid": valid})
    t = await dal.update_tool(db, key, body)
    if not t:
        raise HTTPException(404, "Not found")
    return t


@router.delete("/tools/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(key: str, db: AsyncIOMotorDatabase = Depends(get_db)):
    if not await dal.delete_tool(db, key): raise HTTPException(404, "Not found")
