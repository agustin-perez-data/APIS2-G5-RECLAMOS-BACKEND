"""Consuming Public Spaces' weather alerts (ADR 0014, step 2).

What is covered here is the part that only shows up under a bus that delivers at
least once and sends events with no version number: a redelivery must do
nothing, and an event older than the last one applied must not undo it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import EventoClimatico, EventoProcesado
from app.domain.enums import EstadoEventoClimatico
from app.events import topics
from app.events.handlers import HANDLERS
from app.services.reclamo_service import ReclamoService

DESDE = int(datetime(2026, 11, 4, 18, tzinfo=UTC).timestamp() * 1000)
HASTA = int(datetime(2026, 11, 4, 23, tzinfo=UTC).timestamp() * 1000)


def _id() -> str:
    """The gateway sends `eventId` as a uuid string, and the envelope parses it as one."""
    return str(uuid.uuid4())


def _confirmada(alerta_id: uuid.UUID, *, event_id: str, cuando: datetime, **extra) -> dict:
    datos = {
        "alertaId": str(alerta_id),
        "nivelCriticidad": "ALTA",
        "fenomeno": "TORMENTA_FUERTE",
        "barrios": ["PALERMO", "Belgrano"],
        "ubicaciones": [{"latitud": -34.5755, "longitud": -58.4231}],
        "vigenciaDesde": DESDE,
        "vigenciaHasta": HASTA,
        "actorSub": "admin-demo",
        "temperaturaMinC": None,
        "temperaturaMaxC": None,
    }
    datos.update(extra)
    return {
        "event_id": event_id,
        "event_type": topics.ESPACIOS_CLIMA_CONFIRMADA,
        "occurred_at": cuando.isoformat(),
        "source": "espacios",
        "data": datos,
    }


def _finalizada(alerta_id: uuid.UUID, *, event_id: str, cuando: datetime) -> dict:
    return {
        "event_id": event_id,
        "event_type": topics.ESPACIOS_CLIMA_FINALIZADA,
        "occurred_at": cuando.isoformat(),
        "source": "espacios",
        "data": {"alertaId": str(alerta_id), "finalizadaEn": HASTA, "actorSub": "admin-demo"},
    }


async def _manejar(sobre: dict, session, publisher) -> None:
    await HANDLERS[sobre["event_type"]](sobre, ReclamoService(session, publisher))


@pytest.mark.asyncio
async def test_la_alerta_se_guarda_con_los_barrios_normalizados(session, publisher) -> None:
    alerta_id = uuid.uuid4()
    ahora = datetime.now(UTC)

    await _manejar(_confirmada(alerta_id, event_id=_id(), cuando=ahora), session, publisher)

    guardada = await session.get(EventoClimatico, alerta_id)
    assert guardada is not None
    # "Belgrano" came in mixed case and is stored as a code, so the cross
    # against reclamos.barrio_codigo is a plain comparison.
    assert guardada.barrios == ["PALERMO", "BELGRANO"]
    assert guardada.estado is EstadoEventoClimatico.CONFIRMADA
    # SQLite returns naive datetimes and PostgreSQL aware ones, so compare the
    # instant rather than the representation.
    esperado = datetime.fromtimestamp(DESDE / 1000, tz=UTC)
    assert guardada.vigencia_desde.replace(tzinfo=UTC) == esperado


@pytest.mark.asyncio
async def test_una_reentrega_no_vuelve_a_procesar(session, publisher) -> None:
    # The whole reason eventos_procesados exists: in step 3 this handler
    # notifies every affected neighbour, and the bus delivers at least once.
    alerta_id = uuid.uuid4()
    ahora = datetime.now(UTC)
    event_id = _id()
    sobre = _confirmada(alerta_id, event_id=event_id, cuando=ahora)

    await _manejar(sobre, session, publisher)
    # Exactly the same delivery, a second time.
    await _manejar(dict(sobre), session, publisher)

    assert await session.get(EventoProcesado, event_id) is not None
    guardada = await session.get(EventoClimatico, alerta_id)
    assert guardada is not None


@pytest.mark.asyncio
async def test_un_evento_mas_viejo_no_pisa_al_mas_nuevo(session, publisher) -> None:
    # Two deliveries of the same alert can arrive out of order, and their event
    # has no version field: the bus' timestamp is the only ordering there is.
    alerta_id = uuid.uuid4()
    ahora = datetime.now(UTC)

    nuevo = _confirmada(alerta_id, event_id=_id(), cuando=ahora, nivelCriticidad="CRITICA")
    await _manejar(nuevo, session, publisher)

    viejo = _confirmada(
        alerta_id, event_id=_id(), cuando=ahora - timedelta(hours=2), nivelCriticidad="BAJA"
    )
    await _manejar(viejo, session, publisher)

    guardada = await session.get(EventoClimatico, alerta_id)
    assert guardada is not None
    assert guardada.nivel.value == "CRITICA"


@pytest.mark.asyncio
async def test_una_actualizacion_mas_nueva_si_cambia_el_nivel(session, publisher) -> None:
    alerta_id = uuid.uuid4()
    ahora = datetime.now(UTC)

    await _manejar(
        _confirmada(alerta_id, event_id=_id(), cuando=ahora, nivelCriticidad="BAJA"),
        session,
        publisher,
    )
    await _manejar(
        _confirmada(
            alerta_id,
            event_id=_id(),
            cuando=ahora + timedelta(minutes=30),
            nivelCriticidad="CRITICA",
            barrios=["Caballito"],
        ),
        session,
        publisher,
    )

    guardada = await session.get(EventoClimatico, alerta_id)
    assert guardada is not None
    assert guardada.nivel.value == "CRITICA"
    assert guardada.barrios == ["CABALLITO"]


@pytest.mark.asyncio
async def test_la_alerta_se_finaliza(session, publisher) -> None:
    alerta_id = uuid.uuid4()
    ahora = datetime.now(UTC)

    await _manejar(_confirmada(alerta_id, event_id=_id(), cuando=ahora), session, publisher)
    await _manejar(
        _finalizada(alerta_id, event_id=_id(), cuando=ahora + timedelta(hours=1)),
        session,
        publisher,
    )

    guardada = await session.get(EventoClimatico, alerta_id)
    assert guardada is not None
    assert guardada.estado is EstadoEventoClimatico.FINALIZADA


@pytest.mark.asyncio
async def test_finalizar_una_alerta_que_nunca_llego_no_rompe(session, publisher) -> None:
    # Not an error: Public Spaces can close an alert whose confirmation never
    # reached us, and the webhook must not answer 500 for that.
    await _manejar(
        _finalizada(uuid.uuid4(), event_id=_id(), cuando=datetime.now(UTC)), session, publisher
    )


@pytest.mark.asyncio
async def test_una_alerta_sin_barrios_se_guarda_igual(session, publisher) -> None:
    # Their schema defaults `barrios` to []. That is the case the geographic
    # fallback exists for, so the alert still has to be stored.
    alerta_id = uuid.uuid4()

    await _manejar(
        _confirmada(alerta_id, event_id=_id(), cuando=datetime.now(UTC), barrios=[]),
        session,
        publisher,
    )

    guardada = await session.get(EventoClimatico, alerta_id)
    assert guardada is not None
    assert guardada.barrios == []
    assert guardada.ubicaciones == [{"latitud": -34.5755, "longitud": -58.4231}]
