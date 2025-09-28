# integrations/mcp/cobol/cobol-parser-mcp/src/utils/logging.py
from __future__ import annotations
import json
import logging
import os
import sys
from typing import Any, Mapping

_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "trace": logging.DEBUG,  # treat as debug
}

def _level_from_env() -> int:
    lvl = os.environ.get("LOG_LEVEL", "info").strip().lower()
    return _LEVELS.get(lvl, logging.INFO)

def setup_logging() -> None:
    # Idempotent: reconfigure only once
    if getattr(setup_logging, "_configured", False):
        return
    setup_logging._configured = True  # type: ignore[attr-defined]
    level = _level_from_env()
    handler = logging.StreamHandler(sys.stderr)
    fmt = os.environ.get("LOG_FORMAT", "plain").lower()
    if fmt == "json":
        class _JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                base = {
                    "level": record.levelname.lower(),
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
                if record.exc_info:
                    base["exc_info"] = self.formatException(record.exc_info)
                if hasattr(record, "kv") and isinstance(record.kv, Mapping):
                    base.update(record.kv)  # type: ignore[arg-type]
                return json.dumps(base, ensure_ascii=False)
        handler.setFormatter(_JsonFormatter())
    else:
        formatter = logging.Formatter(
            fmt="[{levelname}] {name}: {message}", style="{"
        )
        handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers[:] = [handler]

def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)

def log_kv(log: logging.Logger, level: int, msg: str, **kv: Any) -> None:
    log.log(level, msg, extra={"kv": kv} if kv else None)
