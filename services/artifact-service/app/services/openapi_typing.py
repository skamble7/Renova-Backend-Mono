# services/artifact-service/app/services/openapi_typing.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Type, Union, Annotated, Literal

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field, create_model
from pydantic.json_schema import JsonSchemaValue, GetJsonSchemaHandler

from app.dal.kind_registry_dal import list_kinds, get_schema_version_entry
from app.models.kind_registry import KindRegistryDoc


# ─────────────────────────────────────────────────────────────
# Base dynamic model that injects per-kind JSON Schema for `data`
# ─────────────────────────────────────────────────────────────

class _ArtifactDynamicBase(BaseModel):
    """
    Minimal envelope for OpenAPI typing. We keep `extra='allow'` so all the
    real fields you already return (artifact_id, lineage, etc.) still appear
    at runtime even if we don’t re-declare each here. The key is that `data`
    gets the real per-kind schema and `kind` is a Literal to enable a
    discriminated union.
    """
    kind: str
    name: str
    data: Dict[str, Any]
    schema_version: Optional[str] = None

    class Config:
        extra = "allow"

    # Populated on concrete subclasses by the factory
    __data_json_schema__: Dict[str, Any] = {}
    __kind_literal__: str = ""

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler: GetJsonSchemaHandler) -> JsonSchemaValue:  # type: ignore[override]
        schema = handler(core_schema)

        # Force `kind` to be a literal enum in OpenAPI (keeps discriminator happy)
        props = schema.get("properties", {})
        if "kind" in props and cls.__kind_literal__:
            props["kind"] = {"type": "string", "enum": [cls.__kind_literal__]}

        # Replace `data` property schema with the registry JSON Schema
        if "data" in props and isinstance(cls.__data_json_schema__, dict) and cls.__data_json_schema__:
            props["data"] = cls.__data_json_schema__

        schema["properties"] = props
        return schema


# ─────────────────────────────────────────────────────────────
# Compiler
# ─────────────────────────────────────────────────────────────

def _safe_name(kind_id: str, version: str) -> str:
    # -> Artifact_cam_contract_api_v1_2_0
    k = re.sub(r"[^A-Za-z0-9_]", "_", kind_id)
    v = re.sub(r"[^A-Za-z0-9_]", "_", version)
    return f"Artifact_{k}_v{v}"

def _make_model(kind_id: str, version: str, data_schema: Dict[str, Any]) -> Type[BaseModel]:
    """
    Create a concrete subclass of _ArtifactDynamicBase with:
      - kind: Literal[kind_id]
      - data: Dict[str, Any] (but OpenAPI overridden to `data_schema`)
    """
    KindLiteralType = Literal[kind_id]  # dynamic Literal

    model = create_model(
        _safe_name(kind_id, version),
        kind=(KindLiteralType, ...),
        name=(str, ...),
        data=(Dict[str, Any], ...),
        schema_version=(Optional[str], None),
        __base__=_ArtifactDynamicBase,
    )
    # Attach schema+literal for OpenAPI overrides
    setattr(model, "__data_json_schema__", data_schema or {})
    setattr(model, "__kind_literal__", kind_id)
    return model


async def compile_discriminated_union(
    db: AsyncIOMotorDatabase,
    *,
    include_deprecated: bool = False,
) -> Tuple[Optional[type], List[Type[BaseModel]], Dict[str, str]]:
    """
    Read all kinds from the registry, compile a concrete Pydantic model for each
    (latest schema_version), and return:
      - Discriminated union type Annotated[Union[...], Field(discriminator="kind")]
      - The list of concrete models
      - Map of kind -> version used (handy for logging/telemetry)
    """
    docs = await list_kinds(db, status=None if include_deprecated else "active", limit=2000)
    if not docs:
        return None, [], {}

    models: List[Type[BaseModel]] = []
    version_map: Dict[str, str] = {}

    for d in docs:
        kd = KindRegistryDoc(**d)
        entry = await get_schema_version_entry(db, kd.id, version=None)
        if not entry:
            continue
        js = entry.get("json_schema") or {}
        if not isinstance(js, dict):
            continue

        m = _make_model(kd.id, entry["version"], js)
        models.append(m)
        version_map[kd.id] = entry["version"]

    if not models:
        return None, [], {}

    # Build an Annotated[Union[...], Field(discriminator='kind')]
    union = Annotated[Union[tuple(models)], Field(discriminator="kind")]  # type: ignore[arg-type]
    return union, models, version_map


# ─────────────────────────────────────────────────────────────
# Patcher for FastAPI routes
# ─────────────────────────────────────────────────────────────

def patch_routes_with_union(app: FastAPI, union_type: type) -> None:
    """
    Patch existing routes so their OpenAPI shows real shapes.
      - GET /artifact/{workspace_id} -> List[UnionType]
      - GET /artifact/{workspace_id}/{artifact_id} -> UnionType
    """
    from typing import List as _List  # avoid shadowing

    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", set())

        if not path.startswith("/artifact"):
            continue

        # Single item
        if path == "/artifact/{workspace_id}/{artifact_id}" and "GET" in methods:
            route.response_model = union_type  # type: ignore[attr-defined]
            route.response_model_include = None
            continue

        # List endpoint
        if path == "/artifact/{workspace_id}" and "GET" in methods:
            route.response_model = _List[union_type]  # type: ignore[attr-defined]
            route.response_model_include = None
            continue
