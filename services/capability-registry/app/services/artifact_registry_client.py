from __future__ import annotations
import httpx
from typing import Iterable, Tuple, List
from ..config import settings

class ArtifactRegistryClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.artifact_service_url).rstrip("/")

    async def validate_kinds(self, kind_ids: Iterable[str]) -> Tuple[List[str], List[str]]:
        """
        Validate kind IDs using artifact-service batch endpoint.
        Returns (valid, invalid).
        """
        ids = list({k for k in kind_ids if k})
        if not ids:
            return [], []

        url = f"{self.base_url}/registry/kinds/exists"
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(url, json={"ids": ids})
        if r.status_code != 200:
            raise RuntimeError(f"Artifact-service returned {r.status_code}: {r.text}")
        data = r.json()
        return data.get("valid", []), data.get("invalid", [])
