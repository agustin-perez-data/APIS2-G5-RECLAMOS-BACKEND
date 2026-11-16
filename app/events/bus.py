"""Consumer of the CityPass+ bus, straight from its Kafka (ADR 0023).

Group 1 writes every event to a topic named after its type, in Confluent's wire
format: a zero byte, the schema id in four bytes and the record in Avro. This
reads those topics, decodes each message against the schema registry and runs
the same `HANDLERS` the webhook runs, through the same translation
(`app.events.entrada`), so an event behaves the same on either road.

It runs inside the API process, as a task started by the lifespan, and only
when `BUS_KAFKA_ENABLED=true`. Guarantees:

* **at-least-once**: the offset is committed after the message was handled. A
  redelivery is harmless: the handlers are idempotent.
* **a message can never stop the topic**: one that cannot be decoded, or that
  no handler accepts, is logged, counted and skipped. Only what may fix itself
  (the database, the registry) is retried.
* **the broker can never stop the API**: every failure of the connection ends
  in a wait and a new attempt, never in an exception out of `run()`.
* **nothing is lost while the service sleeps**: the group's position is pinned
  on the first connection, so what arrives while nobody is listening is read on
  the way back up.
"""

from __future__ import annotations

import asyncio
import io
import json
import ssl
import struct
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import certifi
import fastavro
import httpx
from aiokafka.abc import AbstractTokenProvider
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.core.metrics import EVENTOS_DEL_BUS
from app.db.session import session_scope
from app.events import topics
from app.events.entrada import a_sobre_interno
from app.events.handlers import HANDLERS, Handler
from app.events.producer import EventPublisher
from app.services.reclamo_service import ReclamoService

log = get_logger(__name__)

# Confluent wire format: magic byte + big-endian schema id, then the record.
_MAGIA = 0
_CABECERA = struct.Struct(">bI")

# Label for what could not be tied to one of our topics. Labels are a closed
# set: the type of an unreadable message is, by definition, not known.
_SIN_TOPIC = "otro"

Sesiones = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def _contexto_tls() -> ssl.SSLContext:
    """TLS for the broker: its certificate and its host name are both checked.

    certifi's bundle, the same one httpx trusts, because the system store is
    not the same on every machine this runs on. The two checks are already
    what a client context does; they are spelled out so that weakening them
    takes a visible change.
    """
    contexto = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    contexto.minimum_version = ssl.TLSVersion.TLSv1_2
    contexto.check_hostname = True
    contexto.verify_mode = ssl.CERT_REQUIRED
    contexto.load_verify_locations(cafile=certifi.where())
    return contexto


class MensajeIlegible(ValueError):
    """The message will never decode: retrying it cannot help."""


def a_json(valor: Any) -> Any:
    """What Avro decodes -> what the same event looks like as JSON.

    Avro's logical types come out as Python objects (`timestamp-millis` as a
    datetime, `uuid` as a UUID) while the webhook delivers the same fields as
    numbers and text, which is what the contracts in `contracts.py` describe.
    Converting here keeps one contract for both roads.
    """
    if isinstance(valor, dict):
        return {clave: a_json(v) for clave, v in valor.items()}
    if isinstance(valor, list | tuple):
        return [a_json(v) for v in valor]
    if isinstance(valor, datetime):
        return int(valor.timestamp() * 1000)
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, Decimal):
        return float(valor)
    return valor


class RegistroDeEsquemas:
    """Schemas by id, read from the bus' registry once and kept.

    A schema id never changes meaning, so the cache needs no expiry.
    """

    def __init__(self, url: str, client: httpx.AsyncClient | None = None) -> None:
        self._url = url.rstrip("/")
        self._client = client
        self._propio = client is None
        self._esquemas: dict[int, Any] = {}

    async def esquema(self, schema_id: int) -> Any:
        if schema_id in self._esquemas:
            return self._esquemas[schema_id]
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)

        respuesta = await self._client.get(f"{self._url}/schemas/ids/{schema_id}")
        if respuesta.status_code == httpx.codes.NOT_FOUND:
            raise MensajeIlegible(f"el registro no conoce el esquema {schema_id}")
        # Anything else that is not a 200 is the registry having a bad moment.
        respuesta.raise_for_status()

        crudo = respuesta.json()["schema"]
        esquema = fastavro.parse_schema(json.loads(crudo) if isinstance(crudo, str) else crudo)
        self._esquemas[schema_id] = esquema
        return esquema

    async def cerrar(self) -> None:
        if self._propio and self._client is not None:
            await self._client.aclose()
            self._client = None


async def decodificar(crudo: bytes | None, registro: RegistroDeEsquemas) -> dict[str, Any]:
    """One Kafka message -> the event as the webhook would have delivered it."""
    if not crudo or len(crudo) <= _CABECERA.size:
        raise MensajeIlegible("mensaje vacio o mas corto que su cabecera")
    magia, schema_id = _CABECERA.unpack_from(crudo)
    if magia != _MAGIA:
        raise MensajeIlegible("el mensaje no esta en el formato de Confluent")

    esquema = await registro.esquema(schema_id)
    try:
        evento = fastavro.schemaless_reader(io.BytesIO(crudo[_CABECERA.size :]), esquema)
    except Exception as exc:  # noqa: BLE001 - fastavro raises whatever the bytes provoke
        raise MensajeIlegible(f"no decodifica con el esquema {schema_id}: {exc!r}") from exc
    if not isinstance(evento, dict):
        raise MensajeIlegible(f"el esquema {schema_id} no describe un registro")
    return a_json(evento)


class TokenDelBus(AbstractTokenProvider):
    """`client_credentials` token for the broker's OAUTHBEARER, cached."""

    def __init__(self, cfg: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._cfg = cfg
        self._client = client
        self._token: str | None = None
        self._vence = 0.0

    async def token(self) -> str:
        # Reused until a minute before it expires: they last 15 minutes and the
        # client asks for one on every connection it opens.
        if self._token and time.monotonic() < self._vence - 60:
            return self._token

        datos = {
            "grant_type": "client_credentials",
            "client_id": self._cfg.bus_kafka_client_id,
            "client_secret": self._cfg.bus_kafka_client_secret,
        }
        if self._client is not None:
            respuesta = await self._client.post(self._cfg.bus_kafka_token_url, data=datos)
        else:
            async with httpx.AsyncClient(timeout=10.0) as client:
                respuesta = await client.post(self._cfg.bus_kafka_token_url, data=datos)
        respuesta.raise_for_status()

        cuerpo = respuesta.json()
        self._token = cuerpo["access_token"]
        self._vence = time.monotonic() + float(cuerpo.get("expires_in", 900))
        return self._token


class BusConsumer:
    def __init__(
        self,
        publisher: EventPublisher,
        cfg: Settings | None = None,
        *,
        handlers: dict[str, Handler] | None = None,
        registro: RegistroDeEsquemas | None = None,
        sesiones: Sesiones = session_scope,
    ) -> None:
        self._cfg = cfg or settings
        self._publisher = publisher
        self._handlers = handlers if handlers is not None else HANDLERS
        self._registro = registro or RegistroDeEsquemas(self._cfg.bus_kafka_schema_registry_url)
        self._sesiones = sesiones
        self._consumer: Any = None

        desconocidos = sorted(set(self._cfg.bus_kafka_topics) - set(topics.GATEWAY_A_TOPIC))
        if desconocidos:
            # A topic nobody translates would be read and thrown away forever.
            raise ValueError(
                f"BUS_KAFKA_TOPICS nombra tipos de evento sin handler: {', '.join(desconocidos)}"
            )

    @property
    def topics(self) -> list[str]:
        return list(self._cfg.bus_kafka_topics)

    # --- One message ---------------------------------------------------------

    async def manejar(self, crudo: bytes | None, *, origen: str = "", offset: int = -1) -> str:
        """Handle one message and say what became of it.

        Never raises for the message's own faults. It does for what may fix
        itself before the handler runs (the registry being down), so the caller
        drops the connection and reads the message again.
        """
        resultado, topic = await self._manejar(crudo, origen=origen, offset=offset)
        EVENTOS_DEL_BUS.labels(topic, resultado).inc()
        return resultado

    async def _manejar(self, crudo: bytes | None, *, origen: str, offset: int) -> tuple[str, str]:
        try:
            evento = await decodificar(crudo, self._registro)
        except MensajeIlegible as exc:
            log.warning("bus.mensaje_ilegible", origen=origen, offset=offset, error=str(exc))
            return "ilegible", _SIN_TOPIC

        try:
            traducido = a_sobre_interno(evento)
        except ValueError as exc:
            log.warning("bus.evento_invalido", origen=origen, offset=offset, error=str(exc))
            return "invalido", _SIN_TOPIC
        if traducido is None:
            return "ignorado", _SIN_TOPIC

        topic, interno = traducido
        handler = self._handlers.get(topic)
        if handler is None:
            return "ignorado", _SIN_TOPIC

        event_id = str(interno["event_id"])
        intentos = max(self._cfg.bus_kafka_intentos, 1)
        for intento in range(1, intentos + 1):
            try:
                async with self._sesiones() as session:
                    servicio = ReclamoService(session, self._publisher, cfg=self._cfg)
                    await handler(interno, servicio)
            except ValidationError as exc:
                # The payload does not match the contract: no retry can fix it.
                log.warning(
                    "bus.evento_invalido",
                    topic=topic,
                    event_id=event_id,
                    offset=offset,
                    errores=exc.error_count(),
                )
                return "invalido", topic
            except Exception:  # noqa: BLE001 - isolated per message
                log.exception(
                    "bus.handler_fallo",
                    topic=topic,
                    event_id=event_id,
                    offset=offset,
                    intento=intento,
                )
                if intento < intentos:
                    await asyncio.sleep(self._cfg.bus_kafka_espera_segundos * intento)
            else:
                log.info("bus.evento_procesado", topic=topic, event_id=event_id, offset=offset)
                return "procesado", topic
        return "error", topic

    # --- The connection ------------------------------------------------------

    async def _conectar(self) -> None:
        from aiokafka import AIOKafkaConsumer

        self._consumer = AIOKafkaConsumer(
            *self.topics,
            bootstrap_servers=self._cfg.bus_kafka_bootstrap_servers,
            group_id=self._cfg.bus_kafka_group_id,
            client_id=f"{self._cfg.kafka_client_id}-bus",
            security_protocol="SASL_SSL",
            sasl_mechanism="OAUTHBEARER",
            sasl_oauth_token_provider=TokenDelBus(self._cfg),
            ssl_context=_contexto_tls(),
            # Manual commit: only once the message has been handled.
            enable_auto_commit=False,
            # Only for a group with no position yet; see `_fijar_posicion`.
            auto_offset_reset=self._cfg.bus_kafka_desde,
            # Raw bytes on purpose: a deserializer here would raise inside the
            # iteration, where a bad message cannot be skipped.
        )
        await self._consumer.start()
        log.info("bus.conectado", topics=self.topics, group=self._cfg.bus_kafka_group_id)

    async def _fijar_posicion(self) -> None:
        """Commit where the group stands, for partitions it has no commit on.

        Without this a group that has not handled a message yet has no position,
        and every restart would begin again at the end of the topic: whatever
        arrived while the service was asleep or redeploying would be skipped.
        Alerts are rare, so that would be the normal case, not the odd one.
        """
        for particion in self._consumer.assignment():
            if await self._consumer.committed(particion) is None:
                posicion = await self._consumer.position(particion)
                await self._consumer.commit({particion: posicion})
                log.info(
                    "bus.posicion_fijada",
                    topic=particion.topic,
                    particion=particion.partition,
                    offset=posicion,
                )

    async def _desconectar(self) -> None:
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            try:
                await consumer.stop()
            except Exception:  # noqa: BLE001 - closing a connection that is already broken
                log.warning("bus.cierre_fallido")

    async def run(self) -> None:
        """Read until cancelled, reconnecting after any failure."""
        try:
            while True:
                try:
                    await self._conectar()
                    await self._fijar_posicion()
                    async for mensaje in self._consumer:
                        await self.manejar(
                            mensaje.value, origen=mensaje.topic, offset=mensaje.offset
                        )
                        # Whatever became of it: a message left uncommitted
                        # would be read again forever.
                        await self._consumer.commit()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - the broker must not take the API down
                    log.exception("bus.conexion_caida")
                finally:
                    await self._desconectar()
                await asyncio.sleep(self._cfg.bus_kafka_reconexion_segundos)
        finally:
            await self._registro.cerrar()
            log.info("bus.detenido")
