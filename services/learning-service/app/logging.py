from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict


def _json_formatter(record: logging.LogRecord) -> str:
    payload: Dict[str, Any] = {
        "ts": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
        "level": record.levelname.lower(),
        "logger": record.name,
        "msg": record.getMessage(),
    }
    # Attach extras if present
    for k, v in record.__dict__.items():
        if k in ("args", "msg", "levelname", "name", "exc_info", "exc_text"):
            continue
        if k.startswith("_"):
            continue
        # include correlation id if placed on the record
        if k in ("correlation_id",):
            payload[k] = v
    if record.exc_info:
        payload["exc_info"] = logging.Formatter().formatException(record.exc_info)
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return _json_formatter(record)


def configure_logging() -> None:
    """
    Simple JSON logging to stdout with a configurable level (LOG_LEVEL).
    Plays nice with uvicorn if run under it.
    """
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers (uvicorn may add some)
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)

    # Quiet noisy libs if desired
    logging.getLogger("aio_pika").setLevel(os.getenv("LOG_LEVEL_AIOPIKA", level))
    logging.getLogger("httpx").setLevel(os.getenv("LOG_LEVEL_HTTPX", level))
