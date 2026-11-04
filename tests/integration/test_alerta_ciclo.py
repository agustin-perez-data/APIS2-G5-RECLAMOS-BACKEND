"""Stages 2 and 3 of the weather alert, and the endorsement threshold.

Stage 2 is the claim filed while an alert is live; stage 3 is what happens when
it ends. The threshold is in between: it only drops for a claim under an alert
that is still in force.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import EventoClimatico, Reclamo
from app.domain.enums import (
    CanalOrigen,
    CategoriaReclamo,
    EstadoEventoClimatico,
    EstadoReclamo,
    NivelCriticidad,
    OrigenClasificacion,
    PrioridadReclamo,
)
from app.schemas.reclamo import ReclamoCrear
from app.services.reclamo_service import ReclamoService


def _alerta(
    *,
    nivel: NivelCriticidad = NivelCriticidad.ALTA,
    barrios: list[str] | None = None,
    desde: datetime | None = None,
    estado: EstadoEventoClimatico = EstadoEventoClimatico.CONFIRMADA,
) -> EventoClimatico:
    ahora = datetime.now(UTC)
    return EventoClimatico(
        alerta_id=uuid.uuid4(),
        nivel=nivel,
        fenomeno="TORMENTA_FUERTE",
        barrios=barrios if barrios is not None else ["PALERMO"],
        ubicaciones=[],
        vigencia_desde=desde or (ahora - timedelta(hours=1)),
        vigencia_hasta=ahora + timedelta(hours=4),
        estado=estado,
    )


def _reclamo(
    *,
    barrio: str | None = "Palermo",
    categoria: CategoriaReclamo = CategoriaReclamo.ARBOLADO,
    prioridad: PrioridadReclamo = PrioridadReclamo.BAJA,
    alerta_id: uuid.UUID | None = None,
    estado: EstadoReclamo = EstadoReclamo.RECIBIDO,
) -> Reclamo:
    return Reclamo(
        ciudadano_id=str(uuid.uuid4()),
        titulo="Arbol caido",
        descripcion="Se cayo un arbol",
        categoria=categoria,
        prioridad=prioridad,
        estado=estado,
        canal=CanalOrigen.APP,
        origen_clasificacion=OrigenClasificacion.CIUDADANO,
        barrio=barrio,
        alerta_id=alerta_id,
    )


# --- Stage 2 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_reclamo_nuevo_del_area_queda_bajo_la_alerta(session, publisher) -> None:
    alerta = _alerta(barrios=["PALERMO"])
    session.add(alerta)
    await session.commit()

    service = ReclamoService(session, publisher)
    reclamo = await service.crear(
        ReclamoCrear(
            titulo="Se cayo una rama grande",
            descripcion="Una rama bloquea la vereda por el temporal",
            categoria=CategoriaReclamo.ARBOLADO,
            barrio="palermo",
        ),
        ciudadano_id=str(uuid.uuid4()),
    )

    assert reclamo.alerta_id == alerta.alerta_id
    # ARBOLADO is one of the categories the weather makes worse.
    assert reclamo.prioridad is PrioridadReclamo.ALTA


@pytest.mark.asyncio
async def test_un_reclamo_de_otro_barrio_no_queda_bajo_la_alerta(session, publisher) -> None:
    alerta = _alerta(barrios=["PALERMO"])
    session.add(alerta)
    await session.commit()

    reclamo = await ReclamoService(session, publisher).crear(
        ReclamoCrear(
            titulo="Arbol caido",
            descripcion="Se cayo un arbol",
            categoria=CategoriaReclamo.ARBOLADO,
            barrio="Caballito",
        ),
        ciudadano_id=str(uuid.uuid4()),
    )

    assert reclamo.alerta_id is None


@pytest.mark.asyncio
async def test_una_alerta_que_todavia_no_empezo_no_marca_nada(session, publisher) -> None:
    # Public Spaces can announce a storm for tonight. A claim filed this
    # morning is not under it.
    alerta = _alerta(barrios=["PALERMO"], desde=datetime.now(UTC) + timedelta(hours=5))
    session.add(alerta)
    await session.commit()

    reclamo = await ReclamoService(session, publisher).crear(
        ReclamoCrear(
            titulo="Arbol caido",
            descripcion="Se cayo un arbol",
            categoria=CategoriaReclamo.ARBOLADO,
            barrio="Palermo",
        ),
        ciudadano_id=str(uuid.uuid4()),
    )

    assert reclamo.alerta_id is None


# --- Endorsement threshold -------------------------------------------------


@pytest.mark.asyncio
async def test_bajo_alerta_alta_alcanzan_cinco_adhesiones(session, publisher) -> None:
    alerta = _alerta(nivel=NivelCriticidad.ALTA)
    reclamo = _reclamo(alerta_id=alerta.alerta_id)
    session.add_all([alerta, reclamo])
    await session.commit()

    service = ReclamoService(session, publisher)
    for _ in range(5):
        reclamo = await service.adherir(reclamo.id, str(uuid.uuid4()))

    assert reclamo.adhesiones_count == 5
    assert reclamo.prioridad is PrioridadReclamo.ALTA


@pytest.mark.asyncio
async def test_sin_alerta_siguen_haciendo_falta_diez(session, publisher) -> None:
    # The reduced threshold must never leak into the global rule: lowering it
    # for everyone would change the city's behaviour outside the storm.
    reclamo = _reclamo(alerta_id=None)
    session.add(reclamo)
    await session.commit()

    service = ReclamoService(session, publisher)
    for _ in range(5):
        reclamo = await service.adherir(reclamo.id, str(uuid.uuid4()))

    assert reclamo.adhesiones_count == 5
    assert reclamo.prioridad is PrioridadReclamo.BAJA


@pytest.mark.asyncio
async def test_con_la_alerta_terminada_vuelve_el_umbral_global(session, publisher) -> None:
    # The claim keeps its alerta_id as history, so what decides is the alert's
    # state, not the mark.
    alerta = _alerta(nivel=NivelCriticidad.ALTA, estado=EstadoEventoClimatico.FINALIZADA)
    reclamo = _reclamo(alerta_id=alerta.alerta_id)
    session.add_all([alerta, reclamo])
    await session.commit()

    service = ReclamoService(session, publisher)
    for _ in range(5):
        reclamo = await service.adherir(reclamo.id, str(uuid.uuid4()))

    assert reclamo.prioridad is PrioridadReclamo.BAJA


# --- Stage 3 ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_al_cerrar_se_avisa_y_se_cuentan_los_duplicados(session, publisher) -> None:
    alerta = _alerta()
    uno = _reclamo(alerta_id=alerta.alerta_id, barrio="Palermo")
    dos = _reclamo(alerta_id=alerta.alerta_id, barrio="Palermo")
    otro = _reclamo(alerta_id=alerta.alerta_id, barrio="Belgrano")
    session.add_all([alerta, uno, dos, otro])
    await session.commit()

    resumen = await ReclamoService(session, publisher).cerrar_alerta_climatica(alerta)

    assert resumen.marcados == 3
    assert resumen.abiertos_al_finalizar == 3
    # Two of them are the same neighbourhood and category.
    assert resumen.duplicados_detectados == 1
    assert resumen.avisos_enviados == 3


@pytest.mark.asyncio
async def test_los_duplicados_se_cuentan_pero_NO_se_cierran(session, publisher) -> None:
    # Closing a neighbour's claim because it looks like another one, with nobody
    # looking at it, is not a call this module gets to make.
    alerta = _alerta()
    uno = _reclamo(alerta_id=alerta.alerta_id, barrio="Palermo")
    dos = _reclamo(alerta_id=alerta.alerta_id, barrio="Palermo")
    session.add_all([alerta, uno, dos])
    await session.commit()

    await ReclamoService(session, publisher).cerrar_alerta_climatica(alerta)

    await session.refresh(uno)
    await session.refresh(dos)
    assert uno.estado is EstadoReclamo.RECIBIDO
    assert dos.estado is EstadoReclamo.RECIBIDO


@pytest.mark.asyncio
async def test_el_reclamo_conserva_la_alerta_despues_de_cerrarla(session, publisher) -> None:
    alerta = _alerta()
    reclamo = _reclamo(alerta_id=alerta.alerta_id)
    session.add_all([alerta, reclamo])
    await session.commit()

    await ReclamoService(session, publisher).cerrar_alerta_climatica(alerta)

    await session.refresh(reclamo)
    # It is history: Analytics tells the alert-driven claims apart by this.
    assert reclamo.alerta_id == alerta.alerta_id
