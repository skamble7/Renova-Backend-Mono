from __future__ import annotations
from typing import List
from app.models import CapabilityPack, CapabilitySnapshot

def ensure_pack_capabilities_exist(pack: CapabilityPack, existing_capability_ids: List[str]) -> None:
    """
    Light invariant: all referenced capability_ids should exist.
    (Learning-service will do deeper validations.)
    """
    missing = [cid for cid in (pack.capability_ids or []) if cid not in existing_capability_ids]
    if missing:
        raise ValueError(f"Unknown capability ids in pack: {missing}")

def snapshot_from_capability_doc(doc: dict) -> CapabilitySnapshot:
    """
    Convert a stored GlobalCapability document into a CapabilitySnapshot model.
    """
    return CapabilitySnapshot.model_validate({
        "id": doc["id"],
        "name": doc["name"],
        "description": doc.get("description"),
        "tags": doc.get("tags", []),
        "parameters_schema": doc.get("parameters_schema"),
        "produces_kinds": doc.get("produces_kinds", []),
        "agent": doc.get("agent"),
        "integration": doc.get("integration"),
        "llm_config": doc.get("llm_config"),
    })
