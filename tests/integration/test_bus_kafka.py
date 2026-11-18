"""Events read straight from the bus' Kafka (ADR 0023).

No broker and no network: the messages are built here in the bus' real wire
format, with the schema Public Spaces has registered, and the schema registry
is an in-process HTTP transport. What is covered is what only this road has:
decoding, the Avro types the webhook never showed us, and a loop that has to
survive anything a topic or a broker can throw at it.
"""

from __future__ import annotations

import asyncio
import io
import json
import ssl
import struct
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import aiokafka
import fastavro
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, settings
from app.core.metrics import EVENTOS_DEL_BUS
from app.db.models import EventoClimatico, Reclamo
from app.domain.enums import (
    CanalOrigen,
    CategoriaReclamo,
    EstadoReclamo,
    OrigenClasificacion,
    PrioridadReclamo,
)
from app.events import topics
from app.events.bus import (
    BusConsumer,
    MensajeIlegible,
    RegistroDeEsquemas,
    TokenDelBus,
    _contexto_tls,
    a_json,
    decodificar,
)
from app.events.handlers import HANDLERS

CONFIRMADA = "com.citypass.espacios.CriticidadClimaticaConfirmada"
FINALIZADA = "com.citypass.espacios.CriticidadClimaticaFinalizada"

# The metadata record the gateway inlines in every schema, as read from the
# registry on 2026-11-15.
_METADATA = {
    "type": "record",
    "name": "EventMetadata",
    "namespace": "com.citypass.gateway",
    "fields": [
        {"name": "eventId", "type": "string"},
        {"name": "eventType", "type": "string"},
        {"name": "receivedAt", "type": {"type": "long", "logicalType": "timestamp-millis"}},
        {"name": "source", "type": "string"},
        {"name": "schemaId", "type": "int"},
    ],
}

# Schema 28 of the registry: the enum is what the gateway's webhook chokes on.
ESQUEMA_CONFIRMADA = {
    "type": "record",
    "name": "CriticidadClimaticaConfirmada",
    "namespace": "com.citypass.espacios",
    "fields": [
        {
            "name": "data",
            "type": {
                "type": "record",
                "name": "CriticidadClimaticaConfirmada",
                "namespace": "com.citypass.espacios.data",
                "fields": [
                    {"name": "alertaId", "type": "string"},
                    {
                        "name": "nivelCriticidad",
                        "type": {
                            "type": "enum",
                            "name": "NivelCriticidad",
                            "symbols": ["BAJA", "MEDIA", "ALTA", "CRITICA"],
                        },
                    },
                    {
                        "name": "fenomeno",
                        "type": {
                            "type": "enum",
                            "name": "FenomenoClimatico",
                            "symbols": ["TORMENTA_FUERTE", "LLUVIA_INTENSA", "VIENTO_FUERTE"],
                        },
                    },
                    {
                        "name": "ubicaciones",
                        "type": {
                            "type": "array",
                            "items": {
                                "type": "record",
                                "name": "UbicacionClimatica",
                                "fields": [
                                    {"name": "latitud", "type": "double"},
                                    {"name": "longitud", "type": "double"},
                                ],
                            },
                        },
                    },
                    {"name": "barrios", "type": {"type": "array", "items": "string"}},
                    {
                        "name": "vigenciaDesde",
                        "type": {"type": "long", "logicalType": "timestamp-millis"},
                    },
                    {
                        "name": "vigenciaHasta",
                        "type": {"type": "long", "logicalType": "timestamp-millis"},
                    },
                    {"name": "temperaturaMinC", "type": ["null", "double"], "default": None},
                    {"name": "temperaturaMaxC", "type": ["null", "double"], "default": None},
                    {"name": "actorSub", "type": "string"},
                ],
            },
        },
        {"name": "metadata", "type": _METADATA},
    ],
}

ESQUEMA_FINALIZADA = {
    "type": "record",
    "name": "CriticidadClimaticaFinalizada",
    "namespace": "com.citypass.espacios",
    "fields": [
        {
            "name": "data",
            "type": {
                "type": "record",
                "name": "CriticidadClimaticaFinalizada",
                "namespace": "com.citypass.espacios.data",
                "fields": [
                    {"name": "alertaId", "type": "string"},
                    {
                        "name": "finalizadaEn",
                        "type": {"type": "long", "logicalType": "timestamp-millis"},
                    },
                    {"name": "actorSub", "type": "string"},
                ],
            },
        },
        {"name": "metadata", "type": _METADATA},
    ],
}

ESQUEMAS = {28: ESQUEMA_CONFIRMADA, 27: ESQUEMA_FINALIZADA}


def _mensaje(schema_id: int, evento: dict) -> bytes:
    """Confluent wire format: zero byte, schema id, Avro record."""
    cuerpo = io.BytesIO()
    fastavro.schemaless_writer(cuerpo, fastavro.parse_schema(ESQUEMAS[schema_id]), evento)
    return struct.pack(">bI", 0, schema_id) + cuerpo.getvalue()


def _metadata(tipo: str, schema_id: int, event_id: str | None = None) -> dict:
    return {
        "eventId": event_id or str(uuid.uuid4()),
        "eventType": tipo,
        "receivedAt": datetime.now(UTC),
        "source": "grupo7",
        "schemaId": schema_id,
    }


def confirmada(
    *,
    alerta_id: str | None = None,
    event_id: str | None = None,
    hasta: datetime | None = None,
    barrios: list[str] | None = None,
) -> bytes:
    ahora = datetime.now(UTC)
    return _mensaje(
        28,
        {
            "data": {
                "alertaId": alerta_id or str(uuid.uuid4()),
                "nivelCriticidad": "ALTA",
                "fenomeno": "TORMENTA_FUERTE",
                "ubicaciones": [{"latitud": -34.5738, "longitud": -58.4223}],
                "barrios": barrios if barrios is not None else ["PALERMO"],
                "vigenciaDesde": ahora - timedelta(hours=1),
                "vigenciaHasta": hasta or ahora + timedelta(hours=6),
                "temperaturaMinC": None,
                "temperaturaMaxC": None,
                "actorSub": "U000009",
            },
            "metadata": _metadata(CONFIRMADA, 28, event_id),
        },
    )


def finalizada(alerta_id: str) -> bytes:
    return _mensaje(
        27,
        {
            "data": {
                "alertaId": alerta_id,
                "finalizadaEn": datetime.now(UTC),
                "actorSub": "U000009",
            },
            "metadata": _metadata(FINALIZADA, 27),
        },
    )


def _registro(pedidos: list[str] | None = None, *, caido: bool = False) -> RegistroDeEsquemas:
    def responder(pedido: httpx.Request) -> httpx.Response:
        if pedidos is not None:
            pedidos.append(pedido.url.path)
        if caido:
            return httpx.Response(503)
        schema_id = int(pedido.url.path.rsplit("/", 1)[-1])
        if schema_id not in ESQUEMAS:
            return httpx.Response(404, json={"error_code": 40403})
        # The registry answers the schema as a JSON string inside the JSON.
        return httpx.Response(200, json={"schema": json.dumps(ESQUEMAS[schema_id])})

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    return RegistroDeEsquemas("https://registro.test/api/v1", cliente)


def _cfg(**cambios) -> Settings:
    valores = {
        "bus_kafka_enabled": True,
        "bus_kafka_bootstrap_servers": "broker.test:9092",
        "bus_kafka_token_url": "https://registro.test/auth/oauth/token",
        "bus_kafka_client_id": "cliente",
        "bus_kafka_client_secret": "secreto",
        "bus_kafka_schema_registry_url": "https://registro.test/api/v1",
        "bus_kafka_espera_segundos": 0.0,
        "bus_kafka_reconexion_segundos": 0.0,
    }
    valores.update(cambios)
    return Settings(_env_file=None, **valores)


@pytest.fixture
def sesiones(engine):
    """Sessions of their own per message, as `session_scope` hands out."""
    fabrica = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def abrir():
        async with fabrica() as sesion:
            yield sesion

    return abrir


@pytest.fixture
def bus(publisher, sesiones) -> BusConsumer:
    return BusConsumer(publisher, _cfg(), registro=_registro(), sesiones=sesiones)


async def _reclamo_abierto(session: AsyncSession, barrio: str = "Palermo") -> Reclamo:
    reclamo = Reclamo(
        ciudadano_id=str(uuid.uuid4()),
        titulo="Arbol caido",
        descripcion="Se cayo un arbol en la vereda",
        categoria=CategoriaReclamo.ARBOLADO,
        prioridad=PrioridadReclamo.BAJA,
        estado=EstadoReclamo.RECIBIDO,
        canal=CanalOrigen.APP,
        origen_clasificacion=OrigenClasificacion.CIUDADANO,
        barrio=barrio,
    )
    session.add(reclamo)
    await session.commit()
    return reclamo


def _contado(topic: str, resultado: str) -> float:
    return EVENTOS_DEL_BUS.labels(topic, resultado)._value.get()


# --- Decoding ------------------------------------------------------------------


async def test_decodifica_el_formato_del_bus_como_lo_entregaria_el_webhook() -> None:
    hasta = datetime(2026, 11, 20, 18, 5, tzinfo=UTC)

    evento = await decodificar(confirmada(hasta=hasta), _registro())

    assert evento["metadata"]["eventType"] == CONFIRMADA
    # The enum is plain text and the timestamps are epoch millis again: the
    # same shape `CriticidadClimaticaConfirmada` already validates.
    assert evento["data"]["nivelCriticidad"] == "ALTA"
    assert evento["data"]["vigenciaHasta"] == int(hasta.timestamp() * 1000)
    assert isinstance(evento["metadata"]["receivedAt"], int)


def test_a_json_convierte_los_tipos_logicos_de_avro_en_cualquier_nivel() -> None:
    momento = datetime(2026, 11, 15, 12, tzinfo=UTC)
    identificador = uuid.uuid4()

    convertido = a_json({"a": [{"cuando": momento}], "id": identificador, "n": 3, "t": None})

    assert convertido == {
        "a": [{"cuando": int(momento.timestamp() * 1000)}],
        "id": str(identificador),
        "n": 3,
        "t": None,
    }


@pytest.mark.parametrize(
    "crudo",
    [
        None,
        b"",
        b"\x00\x00\x00",
        b'{"event_type": "espacios.clima.confirmada"}',  # JSON, not the wire format
        struct.pack(">bI", 0, 28) + b"\xff\xff\xff",  # right header, garbage record
        struct.pack(">bI", 0, 999) + b"\x00\x00",  # a schema the registry does not know
    ],
)
async def test_un_mensaje_que_no_decodifica_es_ilegible_y_no_otra_cosa(crudo) -> None:
    registro = _registro()

    with pytest.raises(MensajeIlegible):
        await decodificar(crudo, registro)


async def test_el_esquema_se_pide_una_sola_vez() -> None:
    pedidos: list[str] = []
    registro = _registro(pedidos)

    await decodificar(confirmada(), registro)
    await decodificar(confirmada(), registro)

    assert pedidos == ["/api/v1/schemas/ids/28"]


async def test_el_registro_caido_no_es_un_mensaje_ilegible() -> None:
    """It may come back: the message must be read again, not thrown away."""
    mensaje, registro = confirmada(), _registro(caido=True)

    with pytest.raises(httpx.HTTPStatusError):
        await decodificar(mensaje, registro)


# --- One message ---------------------------------------------------------------


async def test_una_alerta_leida_del_bus_marca_los_reclamos_del_barrio(
    bus, session, publisher
) -> None:
    reclamo = await _reclamo_abierto(session)
    alerta_id = str(uuid.uuid4())
    antes = _contado(topics.ESPACIOS_CLIMA_CONFIRMADA, "procesado")

    resultado = await bus.manejar(confirmada(alerta_id=alerta_id), origen=CONFIRMADA, offset=27)

    assert resultado == "procesado"
    await session.refresh(reclamo)
    assert str(reclamo.alerta_id) == alerta_id
    aplicadas = publisher.eventos_de(topics.CLIMA_APLICADA)
    assert len(aplicadas) == 1
    assert aplicadas[0].data.reclamos_marcados == 1
    assert _contado(topics.ESPACIOS_CLIMA_CONFIRMADA, "procesado") == antes + 1


async def test_una_alerta_vencida_se_guarda_pero_no_marca_ni_avisa(bus, session, publisher) -> None:
    """What a replay or a late read brings: a storm that already ended."""
    reclamo = await _reclamo_abierto(session)
    alerta_id = str(uuid.uuid4())
    ayer = datetime.now(UTC) - timedelta(days=1)

    resultado = await bus.manejar(confirmada(alerta_id=alerta_id, hasta=ayer))

    assert resultado == "procesado"
    await session.refresh(reclamo)
    assert reclamo.alerta_id is None
    assert await session.get(EventoClimatico, uuid.UUID(alerta_id)) is not None
    assert publisher.eventos_de(topics.CLIMA_APLICADA) == []


async def test_el_mismo_evento_por_kafka_y_por_webhook_se_aplica_una_vez(
    bus, session, publisher, client, monkeypatch
) -> None:
    """While both roads are open the same event arrives twice."""
    monkeypatch.setattr(settings, "gateway_webhook_token", "secreto-webhook")
    await _reclamo_abierto(session)
    event_id, alerta_id = str(uuid.uuid4()), str(uuid.uuid4())
    crudo = confirmada(alerta_id=alerta_id, event_id=event_id)

    await bus.manejar(crudo)
    respuesta = await client.post(
        "/api/v1/webhooks/citypass",
        json=await decodificar(crudo, _registro()),
        headers={"X-Webhook-Token": "secreto-webhook"},
    )

    assert respuesta.status_code == 204
    assert len(publisher.eventos_de(topics.CLIMA_APLICADA)) == 1


async def test_la_finalizada_leida_del_bus_cierra_la_alerta(bus, session, publisher) -> None:
    await _reclamo_abierto(session)
    alerta_id = str(uuid.uuid4())
    await bus.manejar(confirmada(alerta_id=alerta_id))

    resultado = await bus.manejar(finalizada(alerta_id))

    assert resultado == "procesado"
    assert len(publisher.eventos_de(topics.CLIMA_LEVANTADA)) == 1


async def test_un_mensaje_ilegible_se_cuenta_y_se_saltea(bus) -> None:
    antes = _contado("otro", "ilegible")

    assert await bus.manejar(b"\x1f\x8b snappy o cualquier cosa") == "ilegible"
    assert _contado("otro", "ilegible") == antes + 1


async def test_un_alerta_id_invalido_no_se_reintenta(publisher, sesiones) -> None:
    """It breaks the contract today and will tomorrow: one look is enough."""
    vistos = 0

    async def handler(raw, service) -> None:
        nonlocal vistos
        vistos += 1
        await HANDLERS[topics.ESPACIOS_CLIMA_CONFIRMADA](raw, service)

    bus = BusConsumer(
        publisher,
        _cfg(),
        handlers={topics.ESPACIOS_CLIMA_CONFIRMADA: handler},
        registro=_registro(),
        sesiones=sesiones,
    )

    assert await bus.manejar(confirmada(alerta_id="1")) == "invalido"
    assert vistos == 1


async def test_un_fallo_pasajero_se_reintenta_y_despues_se_abandona(publisher, sesiones) -> None:
    intentos = 0

    async def falla_dos_veces(raw, service) -> None:
        nonlocal intentos
        intentos += 1
        if intentos < 3:
            raise ConnectionError("la base no responde")

    def bus_con(handler) -> BusConsumer:
        return BusConsumer(
            publisher,
            _cfg(),
            handlers={topics.ESPACIOS_CLIMA_CONFIRMADA: handler},
            registro=_registro(),
            sesiones=sesiones,
        )

    assert await bus_con(falla_dos_veces).manejar(confirmada()) == "procesado"
    assert intentos == 3

    async def falla_siempre(raw, service) -> None:
        raise ConnectionError("la base no responde")

    # Skipped with its own result, so the topic moves on and the counter shows it.
    assert await bus_con(falla_siempre).manejar(confirmada()) == "error"


async def test_un_tipo_sin_handler_se_ignora(publisher, sesiones) -> None:
    bus = BusConsumer(publisher, _cfg(), handlers={}, registro=_registro(), sesiones=sesiones)

    assert await bus.manejar(confirmada()) == "ignorado"


def test_la_conexion_al_broker_valida_el_certificado_y_el_host() -> None:
    contexto = _contexto_tls()

    assert contexto.verify_mode is ssl.CERT_REQUIRED
    assert contexto.check_hostname is True


# --- Configuration -------------------------------------------------------------


def test_encendido_sin_sus_datos_no_arranca() -> None:
    with pytest.raises(ValidationError, match="BUS_KAFKA_CLIENT_SECRET"):
        _cfg(bus_kafka_client_secret="")


def test_el_grupo_tiene_que_ser_del_modulo() -> None:
    """The broker rejects any other: better at boot than in a retry loop."""
    with pytest.raises(ValidationError, match="BUS_KAFKA_GROUP_ID"):
        _cfg(bus_kafka_group_id="reclamos-service")


def test_apagado_no_pide_nada() -> None:
    cfg = Settings(_env_file=None)

    assert cfg.bus_kafka_enabled is False
    # Reading from the end is the default: the history of the topic holds test
    # events, and replaying it over real claims must be a decision.
    assert cfg.bus_kafka_desde == "latest"


def test_un_topic_que_nadie_traduce_no_se_acepta(publisher) -> None:
    cfg = _cfg(bus_kafka_topics=["com.citypass.otro.Evento"])

    with pytest.raises(ValueError, match="sin handler"):
        BusConsumer(publisher, cfg)


# --- The broker's token ----------------------------------------------------------


async def test_el_token_se_pide_con_client_credentials_y_se_reutiliza() -> None:
    pedidos: list[dict] = []

    def responder(pedido: httpx.Request) -> httpx.Response:
        pedidos.append(dict(httpx.QueryParams(pedido.content.decode())))
        return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 900})

    proveedor = TokenDelBus(_cfg(), httpx.AsyncClient(transport=httpx.MockTransport(responder)))

    assert await proveedor.token() == "tok-1"
    assert await proveedor.token() == "tok-1"
    assert pedidos == [
        {"grant_type": "client_credentials", "client_id": "cliente", "client_secret": "secreto"}
    ]


# --- The loop --------------------------------------------------------------------


class _Mensaje:
    def __init__(self, valor: bytes, offset: int) -> None:
        self.value = valor
        self.offset = offset
        self.topic = CONFIRMADA


class _KafkaDeMentira:
    """Stands in for `AIOKafkaConsumer`: a script of connections to play."""

    conexiones: list[list] = []
    instancias: list[_KafkaDeMentira] = []

    def __init__(self, *topics_pedidos, **opciones) -> None:
        self.topics_pedidos = topics_pedidos
        self.opciones = opciones
        self.guion = self.conexiones.pop(0) if self.conexiones else []
        self.commits: list = []
        self.detenido = False
        self.instancias.append(self)

    async def start(self) -> None:
        if self.guion and isinstance(self.guion[0], Exception):
            raise self.guion.pop(0)

    async def stop(self) -> None:
        self.detenido = True

    def assignment(self):
        return {aiokafka.TopicPartition(CONFIRMADA, 0)}

    async def committed(self, particion):
        return None

    async def position(self, particion) -> int:
        return 28

    async def commit(self, offsets=None) -> None:
        self.commits.append(offsets)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.guion:
            await asyncio.Event().wait()  # an idle topic: wait for ever
        siguiente = self.guion.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


@pytest.fixture
def kafka(monkeypatch):
    _KafkaDeMentira.conexiones = []
    _KafkaDeMentira.instancias = []
    monkeypatch.setattr(aiokafka, "AIOKafkaConsumer", _KafkaDeMentira)

    async def sin_red(self) -> dict[str, str]:
        return {}

    # The diagnosis opens real connections: not in a test.
    monkeypatch.setattr(BusConsumer, "_diagnosticar", sin_red)
    return _KafkaDeMentira


async def _hasta(condicion, segundos: float = 5.0) -> None:
    limite = asyncio.get_running_loop().time() + segundos
    while not condicion():
        assert asyncio.get_running_loop().time() < limite, "la condicion nunca se cumplio"
        await asyncio.sleep(0.01)


async def _detener(tarea: asyncio.Task) -> None:
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea


async def test_el_ciclo_fija_la_posicion_y_commitea_cada_mensaje(
    bus, session, publisher, kafka
) -> None:
    await _reclamo_abierto(session)
    # An unreadable message first: the good one behind it must still be handled.
    kafka.conexiones = [[_Mensaje(b"basura", 28), _Mensaje(confirmada(), 29)]]

    tarea = asyncio.create_task(bus.run())
    await _hasta(lambda: kafka.instancias and len(kafka.instancias[0].commits) == 3)
    await _detener(tarea)

    conexion = kafka.instancias[0]
    # First the group's position, pinned because it had none; then one commit
    # per message, the unreadable one included.
    assert conexion.commits[0] == {aiokafka.TopicPartition(CONFIRMADA, 0): 28}
    assert conexion.commits[1:] == [None, None]
    assert len(publisher.eventos_de(topics.CLIMA_APLICADA)) == 1
    assert conexion.detenido
    assert conexion.opciones["enable_auto_commit"] is False
    assert conexion.opciones["group_id"] == "com.citypass.reclamos.worker"
    assert conexion.opciones["auto_offset_reset"] == "latest"
    assert set(conexion.topics_pedidos) == {CONFIRMADA, FINALIZADA}


async def test_el_broker_caido_no_tumba_el_ciclo(bus, session, publisher, kafka) -> None:
    """Down at start, then dropping mid-read: it reconnects both times."""
    await _reclamo_abierto(session)
    kafka.conexiones = [
        [ConnectionError("el broker no responde")],
        [ConnectionError("se corto la conexion")],
        [_Mensaje(confirmada(), 28)],
    ]

    tarea = asyncio.create_task(bus.run())
    await _hasta(lambda: len(publisher.eventos_de(topics.CLIMA_APLICADA)) == 1)
    await _detener(tarea)

    assert len(kafka.instancias) == 3
    assert all(conexion.detenido for conexion in kafka.instancias)


async def test_el_registro_caido_deja_el_mensaje_sin_commitear(publisher, sesiones, kafka) -> None:
    """The connection is dropped instead, so the message is read again."""
    bus = BusConsumer(publisher, _cfg(), registro=_registro(caido=True), sesiones=sesiones)
    kafka.conexiones = [[_Mensaje(confirmada(), 28)], []]

    tarea = asyncio.create_task(bus.run())
    await _hasta(lambda: len(kafka.instancias) == 2)
    await _detener(tarea)

    # Only the pinned position: the message itself was never committed.
    assert kafka.instancias[0].commits == [{aiokafka.TopicPartition(CONFIRMADA, 0): 28}]


# --- When the broker cannot be reached ---------------------------------------------


def test_la_espera_entre_reintentos_crece_hasta_un_tope(publisher) -> None:
    bus = BusConsumer(
        publisher,
        _cfg(bus_kafka_reconexion_segundos=30.0, bus_kafka_reconexion_maxima_segundos=600.0),
    )

    assert [bus._espera(fallos) for fallos in (0, 1, 2, 3, 4, 5, 6, 50)] == [
        30.0,
        30.0,
        60.0,
        120.0,
        240.0,
        480.0,
        600.0,
        600.0,
    ]


class _TokenFijo:
    async def token(self) -> str:
        return "un-token-que-no-debe-aparecer"


async def test_el_diagnostico_dice_que_paso_falla_y_no_muestra_el_token(
    publisher, monkeypatch
) -> None:
    """From outside, a blocked port, a cut handshake and a bad token look alike."""

    async def conexion(host, puerto, **opciones):
        if "ssl" in opciones:
            # What an event loop raises when the far end hangs up mid-handshake.
            raise ConnectionResetError()

        class _Escritor:
            def close(self) -> None:
                pass

        return object(), _Escritor()

    monkeypatch.setattr(asyncio, "open_connection", conexion)
    bus = BusConsumer(publisher, _cfg(), token=_TokenFijo())

    pasos = await bus._diagnosticar()

    assert pasos == {"tcp": "ok", "tls": "ConnectionResetError: ", "token": "ok"}


async def test_el_diagnostico_nunca_suma_una_falla(publisher) -> None:
    bus = BusConsumer(publisher, _cfg(bus_kafka_bootstrap_servers="sin-puerto"), token=_TokenFijo())

    assert list(await bus._diagnosticar()) == ["diagnostico"]


async def test_la_primera_caida_se_diagnostica_y_las_siguientes_no(
    publisher, sesiones, kafka, monkeypatch
) -> None:
    diagnosticos = 0

    async def contar(self) -> dict[str, str]:
        nonlocal diagnosticos
        diagnosticos += 1
        return {"tcp": "ok"}

    monkeypatch.setattr(BusConsumer, "_diagnosticar", contar)
    bus = BusConsumer(publisher, _cfg(), registro=_registro(), sesiones=sesiones)
    kafka.conexiones = [[ConnectionError("x")], [ConnectionError("x")], [ConnectionError("x")], []]

    tarea = asyncio.create_task(bus.run())
    await _hasta(lambda: len(kafka.instancias) == 4)
    await _detener(tarea)

    assert diagnosticos == 1
