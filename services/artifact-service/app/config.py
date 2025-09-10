# services/artifact-service/app/config.py
import os
from pydantic import BaseModel

class Settings(BaseModel):
    app_name: str = "RENOVA Artifact Service"
    host: str = "0.0.0.0"
    port: int = 8011

    # Mongo
    mongo_uri: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    mongo_db: str = os.getenv("MONGO_DB", "renova")

    # RabbitMQ
    rabbitmq_uri: str = os.getenv("RABBITMQ_URI", "amqp://guest:guest@localhost:5672/")
    rabbitmq_exchange: str = os.getenv("RABBITMQ_EXCHANGE", "renova.events")

    # Events: org/tenant segment for versioned routing keys
    # Final RK shape => <events_org>.<service>.<event>.v1
    events_org: str = os.getenv("EVENTS_ORG", "renova")
    platform_events_org: str = os.getenv("PLATFORM_EVENTS_ORG", "platform")

    # Durable named queue for workspace events consumer
    # Set to "" for anonymous auto-delete queue.
    consumer_queue_workspace: str = os.getenv("CONSUMER_QUEUE_WORKSPACE", "platform.workspace.v1")

settings = Settings()
