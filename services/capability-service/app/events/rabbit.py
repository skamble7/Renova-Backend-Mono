# services/capability-service/app/events/rabbit.py
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import aio_pika
from aio_pika import ExchangeType, Message

from app.config import settings
from libs.renova_common.events import rk  # canonical RK helper

logger = logging.getLogger("app.events")


class RabbitBus:
    """
    Minimal async publisher using aio-pika.
    Usage:
        bus = await get_bus().connect()
        await bus.publish(service="capability", event="created", payload={...})
    """
    def __init__(self) -> None:
        self._conn: Optional[aio_pika.RobustConnection] = None
        self._chan: Optional[aio_pika.abc.AbstractChannel] = None
        self._ex: Optional[aio_pika.abc.AbstractExchange] = None
        self._lock = asyncio.Lock()

    async def connect(self) -> "RabbitBus":
        async with self._lock:
            if self._conn and not self._conn.is_closed:
                return self
            logger.info("Rabbit: connecting...")
            self._conn = await aio_pika.connect_robust(settings.rabbitmq_uri)
            self._chan = await self._conn.channel(publisher_confirms=False)
            self._ex = await self._chan.declare_exchange(
                settings.rabbitmq_exchange,
                ExchangeType.TOPIC,
                durable=True,
            )
            logger.info("Rabbit: connected and exchange declared (%s)", settings.rabbitmq_exchange)
        return self

    async def close(self) -> None:
        if self._conn and not self._conn.is_closed:
            await self._conn.close()
            logger.info("Rabbit: connection closed")

    async def publish(self, *, service: str, event: str, payload: dict, version: str = "v1", org: Optional[str] = None, headers: Optional[dict] = None) -> None:
        if not self._ex:
            await self.connect()

        routing_key = rk(org or settings.events_org, service, event, version)
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
