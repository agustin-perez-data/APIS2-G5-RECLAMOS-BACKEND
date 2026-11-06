"""Stages 2 and 3 of the weather alert, and the endorsement threshold.

Stage 2 is the claim filed while an alert is live; stage 3 is what happens when
it ends. The threshold is in between: it only drops for a claim under an alert
that is still in force.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import ActividadMasiva, EventoClimatico, Reclamo
from app.domain.enums import (
    CanalOrigen,
    CategoriaReclamo,
    CausaTipo,
    EstadoEventoClimatico,
    EstadoReclamo,
    NivelCriticidad,
    OrigenClasificacion,
    PrioridadReclamo,
)
from app.events import topics
from app.schemas.reclamo import CambioEstado, ReclamoCrear
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
async def test_el_evento_de_alta_lleva_la_alerta(session, publisher) -> None:
    # Analytics cross-references claims against alerts reading `ReclamoCreado`
    # alone -- the mark on our table is of no use to them. The claim is tied to
    # the alert before the commit, so the event can already carry it. Without
    # this assertion the field travels null forever and nothing looks broken:
    # the contract declares it, the gateway translates it, and the unit test
    # sets it on the envelope by hand.
    alerta = _alerta(barrios=["PALERMO"])
    session.add(alerta)
    await session.commit()

    reclamo = await ReclamoService(session, publisher).crear(
        ReclamoCrear(
            titulo="Se cayo una rama grande",
            descripcion="Una rama bloquea la vereda por el temporal",
            categoria=CategoriaReclamo.ARBOLADO,
            barrio="Palermo",
        ),
        ciudadano_id=str(uuid.uuid4()),
    )

    assert reclamo.alerta_id == alerta.alerta_id
    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert creado.data.alerta_id == alerta.alerta_id


@pytest.mark.asyncio
async def test_sin_alerta_el_evento_de_alta_la_manda_vacia(session, publisher) -> None:
    reclamo = await ReclamoService(session, publisher).crear(
        ReclamoCrear(
            titulo="Arbol caido",
            descripcion="Se cayo un arbol en la vereda",
            categoria=CategoriaReclamo.ARBOLADO,
            barrio="Caballito",
        ),
        ciudadano_id=str(uuid.uuid4()),
    )

    assert reclamo.alerta_id is None
    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert creado.data.alerta_id is None


@pytest.mark.asyncio
async def test_el_evento_de_cambio_de_estado_tambien_lleva_la_alerta(
    session, publisher, usuario_operador
) -> None:
    # `ReclamoEstadoCambiado` declares the same field and the gateway translates
    # it too, so it has the same hole: Movilidad frees a lane on RESUELTO and
    # reads the alert from this event.
    alerta = _alerta(barrios=["PALERMO"])
    session.add(alerta)
    await session.commit()

    service = ReclamoService(session, publisher)
    reclamo = await service.crear(
        ReclamoCrear(
            titulo="Se cayo una rama grande",
            descripcion="Una rama bloquea la vereda por el temporal",
            categoria=CategoriaReclamo.ARBOLADO,
            barrio="Palermo",
        ),
        ciudadano_id=str(uuid.uuid4()),
    )
    await service.cambiar_estado(
        reclamo.id, CambioEstado(estado=EstadoReclamo.ASIGNADO), usuario_operador
    )

    cambiado = publisher.eventos_de(topics.RECLAMO_ESTADO_CAMBIADO)[0]
    assert cambiado.data.alerta_id == alerta.alerta_id


@pytest.mark.asyncio
async def test_la_alerta_viaja_como_causa_del_reclamo(session, publisher) -> None:
    # ADR 0016: Analytics counts "claims caused by a weather event" from
    # `causaTipo`. Until this, the value existed in the enum and never travelled.
    alerta = _alerta(barrios=["PALERMO"])
    session.add(alerta)
    await session.commit()

    await ReclamoService(session, publisher).crear(
        ReclamoCrear(
            titulo="Se cayo una rama grande",
            descripcion="Una rama bloquea la vereda por el temporal",
            categoria=CategoriaReclamo.ARBOLADO,
            barrio="Palermo",
        ),
        ciudadano_id=str(uuid.uuid4()),
    )

    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert creado.data.causa_tipo is CausaTipo.EVENTO_CLIMATICO
    assert creado.data.causa_id == str(alerta.alerta_id)


@pytest.mark.asyncio
async def test_con_alerta_Y_actividad_gana_la_climatica(session, publisher) -> None:
    # The whole point of the precedence, and the only case where it is visible.
    # The alert explains *why* the claim exists; the activity only *where*.
    # The activity is not lost: it keeps travelling in `actividadId`, which is
    # what lets Analytics count the claim on both sides (ADR 0016).
    ahora = datetime.now(UTC)
    alerta = _alerta(barrios=["PALERMO"])
    actividad = ActividadMasiva(
        actividad_origen_id="A-77",
        titulo="Festival de Primavera",
        capacidad=5000,
        latitud=-34.5889,
        longitud=-58.4306,
        inicio=ahora - timedelta(hours=1),
        fin=ahora + timedelta(hours=3),
    )
    session.add_all([alerta, actividad])
    await session.commit()

    await ReclamoService(session, publisher).crear(
        ReclamoCrear(
            titulo="Se cayo una rama grande",
            descripcion="Una rama bloquea la vereda por el temporal",
            categoria=CategoriaReclamo.ARBOLADO,
            barrio="Palermo",
            latitud=-34.5889,
            longitud=-58.4306,
        ),
        ciudadano_id=str(uuid.uuid4()),
    )

    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert creado.data.causa_tipo is CausaTipo.EVENTO_CLIMATICO
    assert creado.data.causa_id == str(alerta.alerta_id)
    # The activity still travels, which is what makes the choice safe.
    assert creado.data.actividad_origen_id == "A-77"


@pytest.mark.asyncio
async def test_sin_alerta_ni_actividad_no_hay_causa(session, publisher) -> None:
    await ReclamoService(session, publisher).crear(
        ReclamoCrear(
            titulo="Arbol caido",
            descripcion="Se cayo un arbol en la vereda del pasaje",
            categoria=CategoriaReclamo.ARBOLADO,
            barrio="Caballito",
        ),
        ciudadano_id=str(uuid.uuid4()),
    )

    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert creado.data.causa_tipo is None
    assert creado.data.causa_id is None


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


# --- Outbound events -------------------------------------------------------


@pytest.mark.asyncio
async def test_al_cerrar_se_publica_el_resumen_sin_datos_personales(session, publisher) -> None:
    from app.events import topics

    alerta = _alerta()
    reclamo = _reclamo(alerta_id=alerta.alerta_id)
    session.add_all([alerta, reclamo])
    await session.commit()

    from app.events.handlers import manejar_criticidad_finalizada

    await manejar_criticidad_finalizada(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": topics.ESPACIOS_CLIMA_FINALIZADA,
            "occurred_at": datetime.now(UTC).isoformat(),
            "data": {"alertaId": str(alerta.alerta_id)},
        },
        ReclamoService(session, publisher),
    )

    publicados = [e for e in publisher.publicados if e[0] == topics.CLIMA_LEVANTADA]
    assert len(publicados) == 1
    payload = publicados[0][2].data.model_dump()
    assert payload["abiertos_al_finalizar"] == 1
    # Counts only: nothing that identifies a neighbour.
    crudo = str(payload)
    assert reclamo.ciudadano_id not in crudo
    assert reclamo.titulo not in crudo
