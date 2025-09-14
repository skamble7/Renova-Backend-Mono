# services/capability-service/app/config.py
from __future__ import annotations
import os
from pydantic import BaseModel


class Settings(BaseModel):
    # App
    app_name: str = "RENOVA Capability Service"
    host: str = "0.0.0.0"
    port: int = 8012  # Capability service default

    # Mongo
    mongo_uri: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    mongo_db: str = os.getenv("MONGO_DB", "renova")

    # RabbitMQ
    rabbitmq_uri: str = os.getenv("RABBITMQ_URI", "amqp://guest:guest@localhost:5672/")
    # We default to the canonical exchange used across Renova per your common events lib.
    rabbitmq_exchange: str = os.getenv("RABBITMQ_EXCHANGE", "raina.events")

    # Events: org/tenant segment for versioned routing keys
    # Final RK shape => <events_org>.<service>.<event>.v1
    events_org: str = os.getenv("EVENTS_ORG", "renova")
    platform_events_org: str = os.getenv("PLATFORM_EVENTS_ORG", "platform")

    # Service identity (optional, useful in logs/events)
    service_name: str = os.getenv("SERVICE_NAME", "capability-service")


settings = Settings()
