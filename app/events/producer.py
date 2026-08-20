"""Publication of domain events onto the bus."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

from pydantic import BaseModel

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.events.contracts import EventEnvelope

log = get_logger(__name__)


class EventPublisher(ABC):
    """Outbound port towards the bus.

    The domain service depends on this abstraction rather than on Kafka, which
    keeps the tests broker-free and lets us swap the technology without
    touching any business logic.
    """

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def _enviar(self, topic: str, key: str | None, envelope: EventEnvelope) -> None: ...

    async def publish(
        self,
        topic: str,
        data: BaseModel,
        *,
        key: str | None = None,
        correlation_id: str | None = None,
        event_version: str = "1.0",
    ) -> EventEnvelope:
        """Wrap the payload and publish it. `event_type` equals the topic name."""
        envelope: EventEnvelope = EventEnvelope(
            event_type=topic,
            event_version=event_version,
            source=settings.service_source,
            correlation_id=correlation_id,
            data=data,
        )
        await self._enviar(topic, key, envelope)
        return envelope


class InMemoryEventPublisher(EventPublisher):
    """Used by the tests and to run without a broker (KAFKA_ENABLED=false).

    Everything published is kept in `self.publicados`, so a test can assert that
    a use case emitted exactly the right event.
    """

    def __init__(self) -> None:
        self.publicados: list[tuple[str, str | None, EventEnvelope]] = []

    async def start(self) -> None:
        log.info("publisher.in_memory.start")

    async def stop(self) -> None:
        self.publicados.clear()

    async def _enviar(self, topic: str, key: str | None, envelope: EventEnvelope) -> None:
        self.publicados.append((topic, key, envelope))
        log.debug("evento.publicado.memoria", topic=topic, event_id=str(envelope.event_id))

    # Test helpers
    def eventos_de(self, topic: str) -> list[EventEnvelope]:
        return [env for t, _, env in self.publicados if t == topic]

    @property
    def topics(self) -> list[str]:
        return [t for t, _, _ in self.publicados]


class KafkaEventPublisher(EventPublisher):
    """Real producer on top of Kafka/Redpanda (aiokafka)."""

    def __init__(self, cfg: Settings | None = None) -> None:
        self._cfg = cfg or settings
        self._producer = None

    async def start(self) -> None:
        from aiokafka import AIOKafkaProducer

        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._cfg.kafka_bootstrap_servers,
            client_id=self._cfg.kafka_client_id,
            # acks=all + idempotence: no loss and no duplicates from producer
            # retries during a rebalance or a broker failure.
            acks="all",
            enable_idempotence=True,
            compression_type="gzip",
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode(),
            key_serializer=lambda k: k.encode() if k else None,
        )
        await self._producer.start()
        log.info("publisher.kafka.start", bootstrap=self._cfg.kafka_bootstrap_servers)

    async def stop(self) -> None:
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
            log.info("publisher.kafka.stop")

    async def _enviar(self, topic: str, key: str | None, envelope: EventEnvelope) -> None:
        if self._producer is None:
            raise RuntimeError("El productor de Kafka no fue inicializado (falta start())")

        headers = [
            ("event_type", envelope.event_type.encode()),
            ("event_version", envelope.event_version.encode()),
            ("source", envelope.source.encode()),
            ("content-type", b"application/json"),
        ]
        if envelope.correlation_id:
            headers.append(("correlation_id", envelope.correlation_id.encode()))

        await self._producer.send_and_wait(
            topic,
            value=envelope.model_dump(mode="json"),
            key=key,
            headers=headers,
        )
        log.info(
            "evento.publicado",
            topic=topic,
            event_id=str(envelope.event_id),
            key=key,
            correlation_id=envelope.correlation_id,
        )


def crear_publisher(cfg: Settings | None = None) -> EventPublisher:
    cfg = cfg or settings
    return KafkaEventPublisher(cfg) if cfg.kafka_enabled else InMemoryEventPublisher()
