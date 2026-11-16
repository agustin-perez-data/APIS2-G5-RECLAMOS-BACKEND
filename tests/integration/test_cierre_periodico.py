"""The auto-close loop that runs inside the process (US-17, ADR 0025).

What `cerrar_resueltos_vencidos` closes is covered through the maintenance
endpoint (`test_cierre_automatico_api.py`). Here it is the clock: that it does
not wait a whole interval for its first pass, that it keeps going after a bad
one, and that the API only starts it when told to.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.domain.enums import EstadoReclamo
from app.events import topics
from app.schemas.reclamo import CambioEstado, ReclamoCrear
from app.services import cierre_periodico
from app.services.cierre_periodico import cerrar_vencidos_una_vez, cierre_automatico_periodico
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID

DATOS = ReclamoCrear(
    titulo="Luminaria apagada en la plaza",
    descripcion="El foco del poste no enciende hace dos semanas y quedo todo oscuro",
)


@pytest.fixture
def sesiones(engine):
    """Sessions of their own per pass, as `session_scope` hands out."""
    fabrica = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def abrir():
        async with fabrica() as sesion:
            yield sesion

    return abrir


async def _resuelto(service: ReclamoService, operador, *, hace_dias: int):
    reclamo = await service.crear(DATOS, CIUDADANO_ID)
    for estado in (EstadoReclamo.ASIGNADO, EstadoReclamo.EN_PROCESO, EstadoReclamo.RESUELTO):
        await service.cambiar_estado(reclamo.id, CambioEstado(estado=estado), operador)
    resuelto = await service.obtener(reclamo.id)
    resuelto.resuelto_at = datetime.now(UTC) - timedelta(days=hace_dias)
    await service.session.commit()
    return reclamo.id


async def _estado(service: ReclamoService, reclamo_id) -> EstadoReclamo:
    reclamo = await service.obtener(reclamo_id)
    await service.session.refresh(reclamo)
    return reclamo.estado


async def _hasta(condicion, segundos: float = 5.0) -> None:
    limite = asyncio.get_running_loop().time() + segundos
    while not condicion():
        assert asyncio.get_running_loop().time() < limite, "la condicion nunca se cumplio"
        await asyncio.sleep(0.01)


async def _detener(tarea: asyncio.Task) -> None:
    tarea.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarea


async def test_una_pasada_cierra_lo_vencido_y_avisa_al_bus(
    service, usuario_operador, publisher, sesiones
) -> None:
    vencido = await _resuelto(service, usuario_operador, hace_dias=8)
    reciente = await _resuelto(service, usuario_operador, hace_dias=2)

    assert await cerrar_vencidos_una_vez(publisher, sesiones) == 1

    assert await _estado(service, vencido) is EstadoReclamo.CERRADO
    assert await _estado(service, reciente) is EstadoReclamo.RESUELTO
    ultimo = publisher.eventos_de(topics.RECLAMO_ESTADO_CAMBIADO)[-1]
    assert ultimo.data.reclamo_id == vencido
    assert ultimo.data.estado_nuevo is EstadoReclamo.CERRADO


async def test_repetir_la_pasada_no_cierra_nada_dos_veces(
    service, usuario_operador, publisher, sesiones
) -> None:
    """A restart or a redeploy runs it again: it must find nothing left."""
    await _resuelto(service, usuario_operador, hace_dias=8)
    await cerrar_vencidos_una_vez(publisher, sesiones)
    publicados = len(publisher.publicados)

    assert await cerrar_vencidos_una_vez(publisher, sesiones) == 0
    assert len(publisher.publicados) == publicados


async def test_el_ciclo_hace_su_primera_pasada_sin_esperar_un_intervalo(
    service, usuario_operador, publisher, sesiones
) -> None:
    """The service sleeps when idle: it may never be up for a whole interval."""
    vencido = await _resuelto(service, usuario_operador, hace_dias=8)

    tarea = asyncio.create_task(
        cierre_automatico_periodico(
            publisher, espera_inicial_segundos=0, intervalo_segundos=3600, sesiones=sesiones
        )
    )
    await _hasta(lambda: len(publisher.eventos_de(topics.RECLAMO_ESTADO_CAMBIADO)) >= 4)
    await _detener(tarea)

    assert await _estado(service, vencido) is EstadoReclamo.CERRADO


async def test_una_pasada_que_falla_no_termina_el_ciclo(publisher, monkeypatch) -> None:
    pasadas = 0

    @asynccontextmanager
    async def base_caida():
        nonlocal pasadas
        pasadas += 1
        raise ConnectionError("la base no responde")
        yield  # pragma: no cover - makes this an async generator

    tarea = asyncio.create_task(
        cierre_automatico_periodico(
            publisher, espera_inicial_segundos=0, intervalo_segundos=0, sesiones=base_caida
        )
    )
    await _hasta(lambda: pasadas >= 3)
    await _detener(tarea)


def test_la_api_no_lo_arranca_si_no_se_le_pide() -> None:
    cfg = Settings(_env_file=None)

    assert cfg.cierre_automatico_en_api is False
    assert cfg.cierre_automatico_espera_inicial_segundos == 60


async def test_la_api_arranca_y_detiene_el_ciclo_con_el_flag(monkeypatch) -> None:
    from app import main

    arrancado = asyncio.Event()
    cancelado = asyncio.Event()

    async def ciclo_de_prueba(publisher, **opciones) -> None:
        assert opciones["espera_inicial_segundos"] == 60
        arrancado.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelado.set()
            raise

    monkeypatch.setattr(main.settings, "cierre_automatico_en_api", True)
    monkeypatch.setattr(cierre_periodico, "cierre_automatico_periodico", ciclo_de_prueba)

    async with main.lifespan(main.app):
        await asyncio.wait_for(arrancado.wait(), timeout=5)

    assert cancelado.is_set()
