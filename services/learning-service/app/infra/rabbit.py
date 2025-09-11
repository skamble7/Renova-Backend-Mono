from __future__ import annotations
import json
import pika
from typing import Optional
from app.config import settings

def publish_event_v1(*, org: str, event: str, payload: dict, headers: Optional[dict] = None):
    """
    Routing key: <org>.<service>.<event>.v1
    """
    rk = f"{org}.{settings.SERVICE_NAME}.{event}.v1"
    props = pika.BasicProperties(
        content_type="application/json",
        headers=headers or {},
        delivery_mode=2,
    )
    params = pika.URLParameters(settings.RABBITMQ_URI)
    conn = pika.BlockingConnection(params)
    try:
        ch = conn.channel()
        ch.exchange_declare(settings.RABBITMQ_EXCHANGE, exchange_type="topic", durable=True)
        ch.basic_publish(
            exchange=settings.RABBITMQ_EXCHANGE,
            routing_key=rk,
            body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            properties=props,
            mandatory=False,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass
