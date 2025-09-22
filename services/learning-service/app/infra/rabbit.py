from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional, Dict, Any

import aio_pika
from aio_pika import ExchangeType, Message

try:
    # Canonical routing-key helper from your shared libs
    from libs.renova_common.events import rk  # rk(org, service, event, version) -> str
except Exception:
    # Fallback if shared lib is absent: compose a simple RK
    def rk(org: str, service: str, event: str, version: str) -> str:
        return f"{org}.{service}.{event}.{version}"


logger = logging.getLogger("app.infra.rabbit")


class RabbitBus:
    """
    Minimal async publisher using aio-pika.

    Usage:
        bus = await get_bus().connect()
        await bus.publish(service="learning", event="run.started", payload={...})
    """

    def __init__(self) -> None:
        self._conn: Optional[aio_pika.RobustConnection] = None
        self._chan: Optional[aio_pika.abc.AbstractChannel] = None
        self._ex: Optional[aio_pika.abc.AbstractExchange] = None
        self._lock = asyncio.Lock()

        # Env-configured settings (kept local so we don't require app.config)
        self._uri = os.getenv("RABBITMQ_URI", "amqp://guest:guest@localhost:5672/")
        self._exchange = os.getenv("RABBITMQ_EXCHANGE", "raina.events")
        self._org = os.getenv("EVENTS_ORG", "renova")

    async def connect(self) -> "RabbitBus":
        async with self._lock:
            if self._conn and not self._conn.is_closed:
                return self
            logger.info("Rabbit: connecting to %s", self._uri)
            self._conn = await aio_pika.connect_robust(self._uri)
            self._chan = await self._conn.channel(publisher_confirms=False)
            self._ex = await self._chan.declare_exchange(
                self._exchange,
                ExchangeType.TOPIC,
                durable=True,
            )
            logger.info("Rabbit: connected; exchange declared (%s)", self._exchange)
        return self

    async def close(self) -> None:
        if self._conn and not self._conn.is_closed:
            await self._conn.close()
            logger.info("Rabbit: connection closed")

    async def publish(
        self,
        *,
        service: str,
        event: str,
        payload: Dict[str, Any],
        version: str = "v1",
        org: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Publish a single event to the topic exchange.

        :param service: logical service scope, e.g. "learning"
        :param event: event name, e.g. "run.started"
        :param payload: JSON-serializable payload
        :param version: version segment for RK (default "v1")
        :param org: org/tenant segment; defaults to EVENTS_ORG
        :param headers: extra AMQP headers (e.g., X-Correlation-ID)
        """
        if not self._ex:
            await self.connect()

        routing_key = rk(org or self._org, service, event, version)
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        message = Message(
            body=body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
            headers=headers or {},
        )
        await self._ex.publish(message, routing_key=routing_key)
        logger.info("Rabbit: published %s (%d bytes)", routing_key, len(body))


_bus: Optional[RabbitBus] = None


def get_bus() -> RabbitBus:
    global _bus
    if _bus is None:
        _bus = RabbitBus()
    return _bus
