# integrations/mcp/cobol/cobol-parser-mcp/src/utils/hashing.py
from __future__ import annotations
import hashlib

def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()
