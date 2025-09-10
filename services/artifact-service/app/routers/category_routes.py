# services/artifact-service/app/routers/category_routes.py
from __future__ import annotations

import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel, Field

from app.db.mongodb import get_db
from app.dal import category_dal as dal
from app.models.category import CategoryCreate, CategoryUpdate, CategoryDoc

logger = logging.getLogger("app.routes.category")

router = APIRouter(
    prefix="/category",
    tags=["category"],
    default_response_class=ORJSONResponse,
)

@router.get("", response_model=list[CategoryDoc])
async def list_categories(q: Optional[str] = Query(default=None), limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    db = await get_db()
    docs = await dal.list_categories(db, q=q, limit=limit, offset=offset)
    return docs

@router.get("/{key}", response_model=CategoryDoc)
async def get_category(key: str):
    db = await get_db()
    doc = await dal.get_category(db, key)
    if not doc:
        raise HTTPException(status_code=404, detail="Category not found")
    return doc

@router.post("", status_code=status.HTTP_201_CREATED, response_model=CategoryDoc)
async def create_or_upsert(body: CategoryCreate, response: Response):
    db = await get_db()
    doc = await dal.upsert_category(db, body)
    return doc

@router.put("/{key}", response_model=CategoryDoc)
async def update_category(key: str, body: CategoryUpdate):
    db = await get_db()
    updated = await dal.update_category(db, key, body)
    if not updated:
        raise HTTPException(status_code=404, detail="Category not found")
    return updated

@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_category(key: str):
    db = await get_db()
    ok = await dal.delete_category(db, key)
    if not ok:
        raise HTTPException(status_code=404, detail="Category not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)

class KeysIn(BaseModel):
    keys: List[str] = Field(..., min_items=1, description="List of category keys, e.g., ['domain','code','data']")

@router.post("/by-keys", response_model=list[CategoryDoc])
async def categories_by_keys(body: KeysIn):
    db = await get_db()
    return await dal.get_categories_by_keys(db, body.keys)
