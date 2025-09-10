from __future__ import annotations

import asyncio, json, logging
from motor.motor_asyncio import AsyncIOMotorDatabase
import aio_pika

from ..config import settings
from ..dal import artifact_dal as dal
from ..models.artifact import WorkspaceSnapshot
from libs.renova_common.events import rk  # ✅ use only rk, not Service

log = logging.getLogger("app.events.workspace_consumer")

# Use raw string for service segment since enum has no WORKSPACE
_SERVICE_SEGMENT = "workspace"

_RK_CREATED = rk(settings.platform_events_org, _SERVICE_SEGMENT, "created")
_RK_UPDATED = rk(settings.platform_events_org, _SERVICE_SEGMENT, "updated")
_RK_DELETED = rk(settings.platform_events_org, _SERVICE_SEGMENT, "deleted")


def _normalize(payload: dict) -> dict:
    """
    Accepts:
      - {"workspace": {...}}
      - {"data": {...}, "meta": {...}}
      - flat {...}
    Ensures '_id' is present (backfills from 'id' when needed).
    """
    data = payload.get("workspace") or payload.get("data") or payload or {}
    wid = data.get("_id") or data.get("id")
    if not wid:
        raise ValueError(f"workspace payload missing id/_id: {payload}")
    if "_id" not in data:
        data = {**data, "_id": wid}
    return data


async def _handle_message_created(db: AsyncIOMotorDatabase, payload: dict) -> None:
    data = _normalize(payload)
    ws = WorkspaceSnapshot.model_validate(data)
    # idempotent
    if await dal.get_parent_doc(db, ws.id):
        log.info("Parent already exists for workspace_id=%s", ws.id)
        return
    created = await dal.create_parent_doc(db, ws)
    log.info("Created WorkspaceArtifactsDoc: workspace_id=%s, doc_id=%s", ws.id, created.id)


async def _handle_message_updated(db: AsyncIOMotorDatabase, payload: dict) -> None:
    data = _normalize(payload)
    ws = WorkspaceSnapshot.model_validate(data)
    await dal.refresh_workspace_snapshot(db, ws)
    log.info("Refreshed workspace snapshot for workspace_id=%s", ws.id)


async def _handle_message_deleted(db: AsyncIOMotorDatabase, payload: dict) -> None:
    data = _normalize(payload)
    wid = data["_id"]
    ok = await dal.delete_parent_doc(db, wid)
    log.info("Deleted parent doc for workspace_id=%s (ok=%s)", wid, ok)


async def run_workspace_created_consumer(db: AsyncIOMotorDatabase, shutdown_event: asyncio.Event) -> None:
    queue_name = settings.consumer_queue_workspace
    while not shutdown_event.is_set():
        try:
            log.info("Connecting to RabbitMQ at %s ...", settings.rabbitmq_uri)
            connection = await aio_pika.connect_robust(settings.rabbitmq_uri)
            async with connection:
                channel = await connection.channel()
                await channel.set_qos(prefetch_count=16)

                exchange = await channel.declare_exchange(
                    settings.rabbitmq_exchange, aio_pika.ExchangeType.TOPIC, durable=True
                )
                queue = await channel.declare_queue(
                    queue_name or "", durable=bool(queue_name), auto_delete=not bool(queue_name)
                )
                await queue.bind(exchange, routing_key=_RK_CREATED)
                await queue.bind(exchange, routing_key=_RK_UPDATED)
                await queue.bind(exchange, routing_key=_RK_DELETED)

                log.info(
                    "Consuming queue=%s exchange=%s rks=[%s, %s, %s]",
                    queue.name, settings.rabbitmq_exchange, _RK_CREATED, _RK_UPDATED, _RK_DELETED
                )

                async with queue.iterator() as q:
                    async for message in q:
                        if shutdown_event.is_set():
                            break
                        async with message.process(requeue=False):
                            try:
                                payload = json.loads(message.body.decode("utf-8"))
                                _ = _normalize(payload)  # validate early
                            except Exception:
                                log.exception("Invalid workspace message; dropping")
                                continue

                            try:
                                if message.routing_key == _RK_CREATED:
                                    await _handle_message_created(db, payload)
                                elif message.routing_key == _RK_UPDATED:
                                    await _handle_message_updated(db, payload)
                                elif message.routing_key == _RK_DELETED:
                                    await _handle_message_deleted(db, payload)
                                else:
                                    log.warning("Unhandled routing key: %s", message.routing_key)
                            except Exception:
                                log.exception("Handler error (rk=%s); continuing", message.routing_key)

        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("workspace consumer error; retrying in 3s")
            await asyncio.sleep(3.0)

    log.info("workspace consumer stopped")
