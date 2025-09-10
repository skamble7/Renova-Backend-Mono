# services/artifact-service/app/events/rabbit.py
import logging
import orjson
import pika
import threading
import time
from typing import Optional, Dict

from ..config import settings
from libs.renova_common.events import EXCHANGE, rk, Service, Version  # ← Renova lib

# Optional: pull correlation/request IDs from middleware if present
try:
    from ..middleware.correlation import request_id_var, correlation_id_var  # type: ignore
except Exception:  # pragma: no cover
    request_id_var = correlation_id_var = None  # type: ignore

logger = logging.getLogger("app.events.rabbit")

_lock = threading.Lock()
_connection: Optional[pika.BlockingConnection] = None
_channel: Optional[pika.adapters.blocking_connection.BlockingChannel] = None


def _exchange_name() -> str:
    """Prefer service config; fallback to lib default."""
    return getattr(settings, "rabbitmq_exchange", None) or getattr(settings, "RABBITMQ_EXCHANGE", EXCHANGE) or EXCHANGE


def _amqp_url() -> str:
    """Support both snake_case and UPPERCASE settings."""
    return getattr(settings, "rabbitmq_uri", None) or getattr(settings, "RABBITMQ_URI")


def _connect():
    global _connection, _channel
    params = pika.URLParameters(_amqp_url())
    _connection = pika.BlockingConnection(params)
    _channel = _connection.channel()
    _channel.exchange_declare(
        exchange=_exchange_name(),
        exchange_type="topic",
        durable=True,
    )
    logger.info("Rabbit: connected and exchange declared", extra={"exchange": _exchange_name()})


def _ensure_conn():
    global _connection, _channel
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
    service: Service | str,
    event: str,
    payload: dict,
    headers: Optional[Dict[str, str]] = None,
    version: str = Version.V1.value,
) -> bool:
    """
    Publish a versioned event to the canonical exchange using the routing key:
        <org>.<service>.<event>.<version>
    Returns True on success (caller should not crash on False).
    """
    hdrs = dict(headers or {})
    try:
        if request_id_var:
            rid = request_id_var.get()
            if rid:
                hdrs.setdefault("x-request-id", rid)
        if correlation_id_var:
            cid = correlation_id_var.get()
            if cid:
                hdrs.setdefault("x-correlation-id", cid)
    except Exception:
        pass

    routing_key = rk(org=org, service=service, event=event, version=version)
    body = orjson.dumps(payload)

    for attempt in (1, 2):
        try:
            _ensure_conn()
            assert _channel is not None
            _channel.basic_publish(
                exchange=_exchange_name(),
                routing_key=routing_key,
                body=body,
                properties=pika.BasicProperties(
                    content_type="application/json",
                    delivery_mode=2,
                    headers=hdrs or None,
                ),
                mandatory=False,
            )
            logger.info("Rabbit: event published", extra={"rk": routing_key, "attempt": attempt})
            return True
        except Exception as e:
            logger.exception("Rabbit publish failed; %s", type(e).__name__, extra={"rk": routing_key, "attempt": attempt})
            _close_dead()
            time.sleep(0.1)
    return False


def publish_event(*args, **kwargs):  # pragma: no cover
    raise RuntimeError("publish_event is removed. Use publish_event_v1(org, service, event, payload).")
