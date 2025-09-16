# integrations/mcp/cobol/cobol-parser-mcp/src/utils/encoding.py
from __future__ import annotations
from typing import Tuple
import codecs

try:
    import chardet  # type: ignore
except Exception:  # pragma: no cover
    chardet = None  # fallback

BOMS = [
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
]

def detect_encoding(raw: bytes, hint: str | None = None) -> Tuple[str, bytes]:
    """Return (encoding, decoded_bytes_without_bom)."""
    if hint:
        try:
            text = raw.decode(hint, errors="strict")
            return hint, raw.lstrip(b"")  # no BOM removal for hinted enc
        except Exception:
            pass

    for bom, enc in BOMS:
        if raw.startswith(bom):
            return enc, raw[len(bom):]

    if chardet:
        guess = chardet.detect(raw) or {}
        enc = guess.get("encoding") or "utf-8"
    else:
        enc = "utf-8"

    return enc, raw
