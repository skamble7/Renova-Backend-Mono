# services/artifact-service/app/models/category.py
from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict

# Note: We allow single-token or dotted keys ("domain", "code", "cobol", "jcl", etc.)
_CATEGORY_KEY_PATTERN = r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)?$|^[a-z][a-z0-9_]*$"

class CategoryBase(BaseModel):
    """Shared fields for Category."""
    key: str = Field(..., min_length=2, pattern=_CATEGORY_KEY_PATTERN)
    name: str = Field(..., min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=2000)
    icon_svg: str = Field(
        ...,
        min_length=10,
        description="Inline SVG (use stroke/fill=currentColor for theme-compat).",
    )

class CategoryCreate(CategoryBase):
    """Payload for creating/upserting a category."""
    pass

class CategoryUpdate(BaseModel):
    """Partial update payload."""
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=2000)
    icon_svg: Optional[str] = Field(default=None, min_length=10)

class CategoryDoc(CategoryBase):
    """Stored Category document."""
    model_config = ConfigDict(populate_by_name=True)
    id: str = Field(alias="_id")
    created_at: datetime
    updated_at: datetime
