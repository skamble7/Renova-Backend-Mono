# integrations/mcp/cobol/cobol-parser-mcp/src/utils/validator.py
from __future__ import annotations
import json
import os
from typing import Any, Dict
from jsonschema import Draft202012Validator

class SchemaRegistry:
    def __init__(self, base_dir: str) -> None:
        self.base_dir = base_dir
        self._schemas: Dict[str, Dict[str, Any]] = {}
        self._validators: Dict[str, Draft202012Validator] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.isdir(self.base_dir):
            return
        for fn in os.listdir(self.base_dir):
            if not fn.endswith(".json"):
                continue
            kind = fn[:-5]  # strip .json
            path = os.path.join(self.base_dir, fn)
            with open(path, "r", encoding="utf-8") as f:
                schema = json.load(f)
            self._schemas[kind] = schema
            self._validators[kind] = Draft202012Validator(schema)

    def validate(self, artifact: Dict[str, Any]) -> list[str]:
        """
        Validate the artifact payload against the kind's schema.

        Accept both envelopes for compatibility:
        - Preferred: artifact["body"]
        - Legacy:    artifact["data"]
        """
        kind = artifact.get("kind")
        validator = self._validators.get(kind)
        if not validator:
            # No schema registered → treat as valid (no blocking).
            return []

        payload = artifact.get("body")
        if payload is None:
            payload = artifact.get("data")

        if payload is None:
            # If there's truly no payload, surface a single, clear error.
            return ["artifact has neither 'body' nor 'data' payload"]

        return [e.message for e in validator.iter_errors(payload)]
