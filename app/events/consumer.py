"""Consumer for events published by other modules.

It runs as a process separate from the API (`python -m app.worker`), so a spike
of messages does not degrade HTTP latency and each side scales on its own.

Guarantees:
* **at-least-once**: the offset is committed after the message is processed.
* **idempotency**: handlers rely on `evento_origen_id`, so a redelivery cannot
  duplicate a claim.
* **poison pill**: a failing message goes to the DLQ and the loop continues; it
  never blocks the partition.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.db.session import session_scope
from app.events import topics
from app.events.contracts import MensajeFallido
from app.events.handlers import HANDLERS, Handler
from app.events.producer import EventPublisher
from app.services.reclamo_service import ReclamoService

log = get_logger(__name__)


class EventConsumer:
    def __init__(
        self,
        publisher: EventPublisher,
        handlers: dict[str, Handler] | None = None,
        cfg: Settings | None = None,
    ) -> None:
        self._cfg = cfg or settings
        self._publisher = publisher
        self._handlers = handlers if handlers is not None else HANDLERS
        self._consumer = None
        self._corriendo = False

    @property
    def topics(self) -> list[str]:
        return list(self._handlers)

    async def start(self) -> None:
        from aiokafka import AIOKafkaConsumer

        self._consumer = AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=self._cfg.kafka_bootstrap_servers,
            group_id=self._cfg.kafka_consumer_group,
            client_id=f"{self._cfg.kafka_client_id}-consumer",
            # Manual commit: only once the handler has finished successfully.
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda v: json.loads(v.decode()),
        )
        await self._consumer.start()
        self._corriendo = True
        log.info("consumer.start", topics=self.topics, group=self._cfg.kafka_consumer_group)

    async def stop(self) -> None:
        self._corriendo = False
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
            log.info("consumer.stop")

    async def procesar(self, topic: str, payload: dict[str, Any]) -> None:
        """Run the topic's handler with a session and service of its own."""
        handler = self._handlers.get(topic)
        if handler is None:
            log.warning("consumer.sin_handler", topic=topic)
            return

        async with session_scope() as session:
            service = ReclamoService(session, self._publisher, cfg=self._cfg)
            await handler(payload, service)

    async def _a_dlq(self, topic: str, payload: dict[str, Any], error: Exception) -> None:
        try:
            await self._publisher.publish(
                topics.DLQ,
                MensajeFallido(topic_original=topic, error=repr(error), payload=payload),
                key=topic,
            )
        except Exception:  # noqa: BLE001 - the DLQ must never take the worker down
            log.exception("consumer.dlq_fallo", topic=topic)

    async def run(self) -> None:
        """Main loop. Runs until `stop()` is called."""
        if self._consumer is None:
            await self.start()

        assert self._consumer is not None
        try:
            async for mensaje in self._consumer:
                try:
                    await self.procesar(mensaje.topic, mensaje.value)
                except Exception as exc:  # noqa: BLE001 - isolated per message
                    log.exception(
                        "consumer.error",
                        topic=mensaje.topic,
                        offset=mensaje.offset,
                        error=str(exc),
                    )
                    await self._a_dlq(mensaje.topic, mensaje.value, exc)
                finally:
                    # Commit anyway after routing to the DLQ: otherwise the same
                    # broken message would block the partition forever.
                    await self._consumer.commit()
        except asyncio.CancelledError:
            log.info("consumer.cancelado")
            raise
        finally:
            await self.stop()
