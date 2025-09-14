# Logging configuration# services/capability-service/app/logging_conf.py
from __future__ import annotations
import logging
import logging.config

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "basic": {
            "format": "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        },
        "uvicorn": {
            "format": "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "basic",
            "level": "INFO",
        },
        "uvicorn": {
            "class": "logging.StreamHandler",
            "formatter": "uvicorn",
            "level": "INFO",
        },
    },
    "loggers": {
        "": {"handlers": ["console"], "level": "INFO"},
        "uvicorn": {"handlers": ["uvicorn"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["uvicorn"], "level": "INFO", "propagate": False},
        "uvicorn.access": {"handlers": ["uvicorn"], "level": "INFO", "propagate": False},
        "app": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

def setup_logging() -> None:
    logging.config.dictConfig(LOGGING_CONFIG)
