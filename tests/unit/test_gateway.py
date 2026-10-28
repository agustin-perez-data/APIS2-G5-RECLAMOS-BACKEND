"""CU-INT-01: translation and publication through the CityPass+ gateway."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.core.config import Settings
from app.domain.enums import (
    CategoriaReclamo,
    EstadoReclamo,
    ObjetoAfectado,
    PrioridadReclamo,
)
from app.events import topics
from app.events.contracts import (
    EventEnvelope,
    ReclamoComentarioCreado,
    ReclamoCreado,
    ReclamoEstadoCambiado,
    ReclamoReclasificado,
)
from app.events.gateway import GatewayEventPublisher, traducir

CREADO_AT = datetime(2026, 11, 1, 15, 0, tzinfo=UTC)


def sobre_creado(categoria: CategoriaReclamo = CategoriaReclamo.TRANSITO) -> EventEnvelope:
    return EventEnvelope(
        event_type=topics.RECLAMO_CREADO,
        correlation_id="corr-1",
        data=ReclamoCreado(
            reclamo_id=uuid.UUID("6f1c9a4e-3c2b-4a5d-9e11-2b7d5c8a1f30"),
            ciudadano_id="vecino-1",
            titulo="Semaforo roto",
            categoria=categoria,
            prioridad=PrioridadReclamo.ALTA,
            estado=EstadoReclamo.RECIBIDO,
            barrio="Centro",
            latitud=-34.6037,
            longitud=-58.3816,
            creado_at=CREADO_AT,
            canal="APP",
            descripcion="El semaforo de la esquina no anda",
            origen_clasificacion="MODELO",
            confianza_clasificacion=0.91,
        ),
    )


def test_reclamo_creado_lleva_los_campos_del_contrato() -> None:
    nombre, datos = traducir(topics.RECLAMO_CREADO, sobre_creado())

    assert nombre == "ReclamoCreado"
    assert datos["reclamoId"] == "6f1c9a4e-3c2b-4a5d-9e11-2b7d5c8a1f30"
    assert datos["categoria"] == "TRANSITO"
    assert datos["origenClasificacion"] == "MODELO"
    assert datos["correlationId"] == "corr-1"
    # Analytics reads createdAt as epoch millis.
    assert datos["createdAt"] == int(CREADO_AT.timestamp() * 1000)


def test_el_alta_lleva_el_objeto_afectado() -> None:
    # Emergencies filters bike lane reports straight from the alta. Before this
    # the field only travelled in ReclamoReclasificado, so a report nobody
    # reclassified never told them what it was about.
    sobre = sobre_creado()
    sobre.data.objeto_afectado = ObjetoAfectado.CICLOVIA

    _, datos = traducir(topics.RECLAMO_CREADO, sobre)

    assert datos["objetoAfectado"] == "CICLOVIA"


def test_el_alta_sin_objeto_afectado_lo_manda_nulo() -> None:
    # It is the neighbour who picks it and the field is optional, so null is the
    # common case: the schema declares it nullable and consumers have to cope.
    _, datos = traducir(topics.RECLAMO_CREADO, sobre_creado())

    assert datos["objetoAfectado"] is None


@pytest.mark.parametrize(
    ("categoria", "afecta"),
    [
        (CategoriaReclamo.TRANSITO, True),
        (CategoriaReclamo.BACHES, True),
        (CategoriaReclamo.ARBOLADO, True),
        (CategoriaReclamo.ALUMBRADO, False),
        (CategoriaReclamo.RUIDOS, False),
    ],
)
def test_afecta_circulacion_depende_de_la_categoria(
    categoria: CategoriaReclamo, afecta: bool
) -> None:
    _, datos = traducir(topics.RECLAMO_CREADO, sobre_creado(categoria))
    assert datos["afectaCirculacion"] is afecta


def test_cambio_de_estado_sale_como_reclamo_actualizado() -> None:
    sobre = EventEnvelope(
        event_type=topics.RECLAMO_ESTADO_CAMBIADO,
        data=ReclamoEstadoCambiado(
            reclamo_id=uuid.uuid4(),
            ciudadano_id="vecino-1",
            estado_anterior=EstadoReclamo.EN_PROCESO,
            estado_nuevo=EstadoReclamo.RESUELTO,
            cambiado_por="operador-1",
            cambiado_at=CREADO_AT,
        ),
    )

    nombre, datos = traducir(topics.RECLAMO_ESTADO_CAMBIADO, sobre)

    assert nombre == "ReclamoActualizado"
    assert datos["estadoNuevo"] == "RESUELTO"
    assert datos["estadoAnterior"] == "EN_PROCESO"
    assert datos["updatedAt"] == int(CREADO_AT.timestamp() * 1000)


def test_la_reclasificacion_sale_con_afecta_circulacion_antes_y_despues() -> None:
    # The flag is what Mobility, Emergencies and Waste actually act on, so we
    # send it computed instead of making each of them derive it again.
    sobre = EventEnvelope(
        event_type=topics.RECLAMO_RECLASIFICADO,
        correlation_id="corr-1",
        data=ReclamoReclasificado(
            reclamo_id=uuid.uuid4(),
            ciudadano_id="7c3a1f5e-9b2d-4e61-8a07-5d4c2b9e1f83",
            categoria_anterior=CategoriaReclamo.RUIDOS,
            categoria_nueva=CategoriaReclamo.TRANSITO,
            prioridad_anterior=PrioridadReclamo.BAJA,
            prioridad_nueva=PrioridadReclamo.ALTA,
            titulo="Auto sobre la vereda",
            descripcion="Hay un vehiculo arriba de la vereda hace dos dias",
            reclasificado_por="operador-1",
            reclasificado_at=CREADO_AT,
        ),
    )

    nombre, datos = traducir(topics.RECLAMO_RECLASIFICADO, sobre)

    assert nombre == "ReclamoReclasificado"
    assert datos["categoriaAnterior"] == "RUIDOS"
    assert datos["categoriaNueva"] == "TRANSITO"
    assert datos["afectaCirculacionAnterior"] is False
    assert datos["afectaCirculacionNueva"] is True
    assert datos["correlationId"] == "corr-1"
    assert datos["reclasificadoAt"] == int(CREADO_AT.timestamp() * 1000)


def test_los_eventos_internos_no_salen_al_gateway() -> None:
    sobre = EventEnvelope(
        event_type=topics.RECLAMO_COMENTARIO_CREADO,
        data=ReclamoComentarioCreado(
            comentario_id=uuid.uuid4(),
            reclamo_id=uuid.uuid4(),
            ciudadano_id="vecino-1",
            autor_id="vecino-2",
            es_oficial=False,
            created_at=CREADO_AT,
        ),
    )
    assert traducir(topics.RECLAMO_COMENTARIO_CREADO, sobre) is None


def _config() -> Settings:
    return Settings(
        gateway_enabled=True,
        gateway_url="http://gateway",
        gateway_token_url="http://auth/oauth/token",
        gateway_client_id="svc-reclamos",
        gateway_client_secret="secreto",
    )


async def test_publica_con_token_y_lo_reutiliza() -> None:
    pedidos: list[httpx.Request] = []

    def responder(request: httpx.Request) -> httpx.Response:
        pedidos.append(request)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 900})
        return httpx.Response(202, json={})

    publisher = GatewayEventPublisher(
        _config(), httpx.AsyncClient(transport=httpx.MockTransport(responder))
    )
    sobre = sobre_creado()
    await publisher.publish(topics.RECLAMO_CREADO, sobre.data, correlation_id="corr-1")
    await publisher.publish(topics.RECLAMO_CREADO, sobre.data, correlation_id="corr-1")

    tokens = [p for p in pedidos if p.url.path == "/oauth/token"]
    eventos = [p for p in pedidos if p.url.path.endswith("/events")]
    assert len(tokens) == 1
    assert len(eventos) == 2
    assert eventos[0].url.path == "/api/v1/event-types/com.citypass.reclamos.ReclamoCreado/events"
    assert eventos[0].headers["Authorization"] == "Bearer tok-1"
    assert json.loads(eventos[0].content)["afectaCirculacion"] is True


async def test_un_rechazo_por_contrato_no_se_reintenta_ni_rompe_el_request() -> None:
    llamadas = 0

    def responder(request: httpx.Request) -> httpx.Response:
        nonlocal llamadas
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 900})
        llamadas += 1
        return httpx.Response(400, json={"detail": "falta reclamoId"})

    publisher = GatewayEventPublisher(
        _config(), httpx.AsyncClient(transport=httpx.MockTransport(responder))
    )
    await publisher.publish(topics.RECLAMO_CREADO, sobre_creado().data)

    assert llamadas == 1
