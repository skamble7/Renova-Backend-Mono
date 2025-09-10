# services/capability-registry/app/events/rabbit.py
from __future__ import annotations

import logging
import time
import threading
from typing import Optional, Dict

import orjson
import pika

from ..config import settings
from libs.renova_common.events import rk, Service, Version

logger = logging.getLogger("capability.events.rabbit")

_lock = threading.Lock()
_connection: Optional[pika.BlockingConnection] = None
_channel: Optional[pika.adapters.blocking_connection.BlockingChannel] = None


def _exchange_name() -> str:
    # Prefer service config; fall back to shared constant if you ever add it.
    return getattr(settings, "rabbitmq_exchange", "renova.events")


def _amqp_url() -> str:
    return getattr(settings, "rabbitmq_uri")


def _connect():
    global _connection, _channel
    params = pika.URLParameters(_amqp_url())
    _connection = pika.BlockingConnection(params)
    _channel = _connection.channel()
    _channel.exchange_declare(exchange=_exchange_name(), exchange_type="topic", durable=True)
    logger.info("Rabbit: connected and exchange declared", extra={"exchange": _exchange_name()})


def _ensure():
    global _channel
    if _channel and _channel.is_open:
        return
    with _lock:
        if _channel and _channel.is_open:
            return
        _connect()


def _close_dead():
    global _connection, _channel
    try:
        if _channel and _channel.is_open:
            _channel.close()
    except Exception:
        pass
    try:
        if _connection and _connection.is_open:
            _connection.close()
    except Exception:
        pass
    _channel = None
    _connection = None


def publish_event_v1(
    *,
    org: str,
    event: str,
    payload: dict,
    headers: Optional[Dict[str, str]] = None,
    version: str = Version.V1.value,
) -> bool:
    """
    Publish a versioned capability event:
        <org>.capability.<event>.<version>
    Example:
        publish_event_v1(org="renova", event="pack.registered", payload={...})
    Returns True on success; retries once after reconnect on failure.
    """
    routing_key = rk(org=org, service=Service.CAPABILITY, event=event, version=version)
    body = orjson.dumps(payload)

    for attempt in (1, 2):
        try:
            _ensure()
            assert _channel is not None
            _channel.basic_publish(
                exchange=_exchange_name(),
                routing_key=routing_key,
                body=body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                    headers=headers or None,
                ),
                mandatory=False,
            )
            logger.info("Rabbit: event published", extra={"routing_key": routing_key, "attempt": attempt})
            return True
        except Exception as e:
            logger.exception("Rabbit publish failed; %s", type(e).__name__,
                             extra={"routing_key": routing_key, "attempt": attempt})
            _close_dead()
            time.sleep(0.1)  # tiny backoff, then one retry
    return False


# Hard deprecation of legacy function to avoid accidental use
def publish_event(*args, **kwargs):  # pragma: no cover
    raise RuntimeError(
        "publish_event is removed. Use publish_event_v1(org, event, payload) with versioned routing keys."
    )
