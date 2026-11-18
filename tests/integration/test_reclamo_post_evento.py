"""Claims over an event that already ended (CASO-RECLAMOS-POST-EVENTO).

`EventoFinalizado` arrives from Public Spaces; a citizen then files a claim over
its `reservaId`. The handler and the service are exercised directly, like the
other handlers: no broker and no gateway needed.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.exceptions import EventoNoFinalizado, PlazoDeReclamoVencido
from app.db.models import Reclamo, ReservaFinalizada
from app.domain.enums import CausaTipo
from app.events import topics
from app.events.handlers import HANDLERS, manejar_evento_finalizado
from app.events.producer import InMemoryEventPublisher
from app.schemas.reclamo import ReclamoCrear
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID

HORA_MS = 3_600_000


def evento_finalizado(reserva_id: str = "RES-100", *, fin_ms: int | None = None) -> dict:
    """What the bus delivers for `com.citypass.espacios.EventoFinalizado`."""
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": topics.ESPACIOS_EVENTO_FINALIZADO,
        "occurred_at": datetime.now(UTC).isoformat(),
        "source": "espacios",
        "data": {
            "reservaId": reserva_id,
            "fin": fin_ms if fin_ms is not None else int(time.time() * 1000) - HORA_MS,
            "asistentesReales": 480,
        },
    }


def reclamo_sobre(reserva_id: str | None) -> ReclamoCrear:
    return ReclamoCrear(
        titulo="Quedo basura despues del recital",
        descripcion="Los contenedores de la plaza quedaron desbordados al terminar el evento",
        reserva_id=reserva_id,
    )


async def contar_reclamos(session) -> int:
    return (await session.execute(select(func.count()).select_from(Reclamo))).scalar_one()


# --- EventoFinalizado ----------------------------------------------------------
async def test_el_evento_finalizado_guarda_la_reserva_y_su_fin(
    session, publisher: InMemoryEventPublisher
) -> None:
    service = ReclamoService(session, publisher)
    fin_ms = 1_793_270_400_000

    await manejar_evento_finalizado(evento_finalizado("RES-1", fin_ms=fin_ms), service)

    guardada = await session.get(ReservaFinalizada, "RES-1")
    assert guardada is not None
    assert guardada.fin_ms == fin_ms


async def test_una_reentrega_no_duplica_la_reserva(
    session, publisher: InMemoryEventPublisher
) -> None:
    # The gateway is at-least-once: the same delivery can arrive twice.
    service = ReclamoService(session, publisher)
    evento = evento_finalizado("RES-2")

    await manejar_evento_finalizado(evento, service)
    await manejar_evento_finalizado(evento, service)

    total = (
        await session.execute(select(func.count()).select_from(ReservaFinalizada))
    ).scalar_one()
    assert total == 1


def test_el_webhook_conoce_el_evento_y_su_handler() -> None:
    assert topics.GATEWAY_A_TOPIC["com.citypass.espacios.EventoFinalizado"] == (
        topics.ESPACIOS_EVENTO_FINALIZADO
    )
    assert HANDLERS[topics.ESPACIOS_EVENTO_FINALIZADO] is manejar_evento_finalizado


# --- Claim over a reservation ---------------------------------------------------
async def test_un_reclamo_sobre_un_evento_que_no_termino_se_rechaza(
    session, publisher: InMemoryEventPublisher
) -> None:
    service = ReclamoService(session, publisher)

    with pytest.raises(EventoNoFinalizado) as error:
        await service.crear(reclamo_sobre("RES-NUNCA-TERMINO"), CIUDADANO_ID)

    assert error.value.status_code == 409
    # Refused before anything is stored or published.
    assert await contar_reclamos(session) == 0
    assert publisher.eventos_de(topics.RECLAMO_CREADO) == []


async def test_un_reclamo_dentro_del_plazo_se_acepta_y_la_reserva_es_la_causa(
    session, publisher: InMemoryEventPublisher
) -> None:
    service = ReclamoService(session, publisher)
    await manejar_evento_finalizado(evento_finalizado("RES-3"), service)

    reclamo = await service.crear(reclamo_sobre("RES-3"), CIUDADANO_ID)

    assert reclamo.reserva_id == "RES-3"
    # The reservation is the correlation id unless the caller brings its own.
    assert reclamo.correlation_id == "RES-3"
    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert creado.correlation_id == "RES-3"
    assert creado.data.causa_tipo == CausaTipo.RESERVA
    assert creado.data.causa_id == "RES-3"


async def test_un_reclamo_con_el_plazo_vencido_se_rechaza(
    session, publisher: InMemoryEventPublisher
) -> None:
    service = ReclamoService(session, publisher)
    hace_mas_que_la_ventana = int(time.time() * 1000) - settings.reclamo_ventana_ms - HORA_MS
    await manejar_evento_finalizado(
        evento_finalizado("RES-4", fin_ms=hace_mas_que_la_ventana), service
    )

    with pytest.raises(PlazoDeReclamoVencido) as error:
        await service.crear(reclamo_sobre("RES-4"), CIUDADANO_ID)

    assert error.value.status_code == 409
    assert await contar_reclamos(session) == 0


async def test_un_reclamo_sin_reserva_sigue_funcionando_igual(
    session, publisher: InMemoryEventPublisher
) -> None:
    # A pothole has no reservation: nothing about the claim changes.
    service = ReclamoService(session, publisher)

    reclamo = await service.crear(reclamo_sobre(None), CIUDADANO_ID)

    assert reclamo.reserva_id is None
    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert creado.data.causa_tipo is None
    assert creado.data.causa_id is None


async def test_el_correlation_id_del_llamador_no_se_pisa(
    session, publisher: InMemoryEventPublisher
) -> None:
    service = ReclamoService(session, publisher)
    await manejar_evento_finalizado(evento_finalizado("RES-5"), service)

    reclamo = await service.crear(reclamo_sobre("RES-5"), CIUDADANO_ID, correlation_id="req-propio")

    assert reclamo.correlation_id == "req-propio"


# --- API ------------------------------------------------------------------------
async def test_la_api_responde_409_si_el_evento_no_termino(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    respuesta = await client.post(
        "/api/v1/reclamos",
        json={
            "titulo": "Quedo basura despues del recital",
            "descripcion": "Los contenedores de la plaza quedaron desbordados al terminar",
            "reserva_id": "RES-SIN-FINALIZAR",
        },
        headers=auth(token_ciudadano),
    )

    assert respuesta.status_code == 409, respuesta.text
    assert respuesta.json()["code"] == "evento_no_finalizado"
