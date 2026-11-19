from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.exceptions import (
    EventoCanceladoError,
    EventoNoFinalizado,
    PlazoDeReclamoVencido,
)
from app.db.models.evento_reclamable import EventoReclamable
from app.services.evento_reclamable_service import EventoReclamableService


def _session(evento=None):
    resultado = SimpleNamespace(scalar_one_or_none=lambda: evento)
    return SimpleNamespace(
        execute=AsyncMock(return_value=resultado),
        add=Mock(),
        commit=AsyncMock(),
    )


def _fecha_fin():
    return datetime(2026, 11, 1, tzinfo=UTC)


def _datos(estado="PUBLICADO"):
    return SimpleNamespace(
        evento_id="evento-123",
        fin=_fecha_fin(),
        estado=estado,
    )


@pytest.mark.asyncio
async def test_registra_evento_publicado():
    session = _session()
    await EventoReclamableService(session).registrar_publicado(_datos())
    evento = session.add.call_args.args[0]
    assert isinstance(evento, EventoReclamable)
    assert evento.evento_id == "evento-123"
    assert evento.fin_ms == int(_fecha_fin().timestamp() * 1000)
    assert evento.cancelado is False
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_actualiza_evento_existente():
    existente = SimpleNamespace(evento_id="evento-123", fin_ms=0, cancelado=False)
    session = _session(existente)
    await EventoReclamableService(session).registrar_publicado(_datos())
    assert existente.fin_ms == int(_fecha_fin().timestamp() * 1000)
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_evento_publicado_con_estado_cancelado():
    session = _session()
    await EventoReclamableService(session).registrar_publicado(_datos("CANCELLED"))
    assert session.add.call_args.args[0].cancelado is True


@pytest.mark.asyncio
async def test_marca_cancelado_un_evento_nuevo():
    session = _session()
    await EventoReclamableService(session).marcar_cancelado("evento-123")
    evento = session.add.call_args.args[0]
    assert evento.evento_id == "evento-123"
    assert evento.fin_ms is None
    assert evento.cancelado is True


@pytest.mark.asyncio
async def test_marca_cancelado_un_evento_existente():
    existente = SimpleNamespace(evento_id="evento-123", fin_ms=1000, cancelado=False)
    session = _session(existente)
    await EventoReclamableService(session).marcar_cancelado("evento-123")
    assert existente.cancelado is True
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_evento_inexistente_no_es_reclamable():
    with pytest.raises(EventoNoFinalizado):
        await EventoReclamableService(_session()).validar_reclamable("evento-123", ahora_ms=1000)


@pytest.mark.asyncio
async def test_evento_cancelado_no_es_reclamable():
    evento = SimpleNamespace(fin_ms=1000, cancelado=True)
    with pytest.raises(EventoCanceladoError):
        await EventoReclamableService(_session(evento)).validar_reclamable(
            "evento-123", ahora_ms=2000
        )


@pytest.mark.asyncio
async def test_evento_sin_fecha_fin_no_es_reclamable():
    evento = SimpleNamespace(fin_ms=None, cancelado=False)
    with pytest.raises(EventoNoFinalizado):
        await EventoReclamableService(_session(evento)).validar_reclamable(
            "evento-123", ahora_ms=2000
        )


@pytest.mark.asyncio
async def test_evento_que_aun_no_termino_no_es_reclamable():
    evento = SimpleNamespace(fin_ms=3000, cancelado=False)
    with pytest.raises(EventoNoFinalizado):
        await EventoReclamableService(_session(evento)).validar_reclamable(
            "evento-123", ahora_ms=2000
        )


@pytest.mark.asyncio
async def test_plazo_de_siete_dias_vencido():
    fin_ms = 1000
    evento = SimpleNamespace(fin_ms=fin_ms, cancelado=False)
    ahora_ms = fin_ms + int(timedelta(days=7).total_seconds() * 1000) + 1
    with pytest.raises(PlazoDeReclamoVencido):
        await EventoReclamableService(_session(evento)).validar_reclamable(
            "evento-123", ahora_ms=ahora_ms
        )


@pytest.mark.asyncio
async def test_evento_reclamable_dentro_de_los_siete_dias():
    fin_ms = 1000
    evento = SimpleNamespace(fin_ms=fin_ms, cancelado=False)
    ahora_ms = fin_ms + int(timedelta(days=3).total_seconds() * 1000)
    assert (
        await EventoReclamableService(_session(evento)).validar_reclamable(
            "evento-123", ahora_ms=ahora_ms
        )
        is None
    )


@pytest.mark.asyncio
async def test_evento_reclamable_exactamente_al_limite_de_siete_dias():
    fin_ms = 1000
    evento = SimpleNamespace(fin_ms=fin_ms, cancelado=False)
    ahora_ms = fin_ms + int(timedelta(days=7).total_seconds() * 1000)
    assert (
        await EventoReclamableService(_session(evento)).validar_reclamable(
            "evento-123", ahora_ms=ahora_ms
        )
        is None
    )
