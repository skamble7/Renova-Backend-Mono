# services/capability-service/app/config.py
import os
from pydantic import BaseModel

class Settings(BaseModel):
    app_name: str = "Renova Capability Service"
    host: str = "0.0.0.0"
    # You said you use 9012
    port: int = int(os.getenv("PORT", "9012"))

    # Mongo
    mongo_uri: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    mongo_db: str = os.getenv("MONGO_DB", "renova")

    # RabbitMQ (shared Raina broker)
    rabbitmq_uri: str = os.getenv("RABBITMQ_URI", "amqp://raina:raina@host.docker.internal:5672/")
    rabbitmq_exchange: str = os.getenv("RABBITMQ_EXCHANGE", "raina.events")

    # Event org/tenant segment for routing keys
    events_org: str = os.getenv("EVENTS_ORG", "renova")

    # Artifact-service base URL used for kind validation
    artifact_service_url: str = os.getenv("ARTIFACT_SERVICE_URL", "http://renova-artifact-service:9011")

# 👇 THIS is what the import expects
settings = Settings()

# (optional, tidy)
__all__ = ["Settings", "settings"]
