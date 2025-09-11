# services/learning-service/app/logging.py
import structlog, logging, sys

def setup_logging():
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.JSONRenderer()],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True
    )
    return structlog.get_logger()
