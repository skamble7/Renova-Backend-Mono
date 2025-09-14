# services/capability-service/app/middleware/__init__.py
from .cors import add_cors
from .logging import install_request_logging
from .error_handlers import add_error_handlers

__all__ = ["add_cors", "install_request_logging", "add_error_handlers"]
