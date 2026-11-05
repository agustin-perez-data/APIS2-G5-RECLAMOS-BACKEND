"""The weather alert, as the API shows it (G5D-449).

The front needs to tell a neighbour that their claim is under an alert, and an
operator needs to see it in the queue. What matters here is that a finished
alert stops showing: the claim keeps its `alerta_id` as history, so the mark
alone would say the wrong thing forever.
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
from app.schemas.reclamo import (
    ReclamoBandeja,
    ReclamoDetalle,
    ReclamoListado,
    ReclamoResumen,
)


def _alerta(
    *,
    nivel: NivelCriticidad = NivelCriticidad.ALTA,
    estado: EstadoEventoClimatico = EstadoEventoClimatico.ACTIVA,
) -> EventoClimatico:
    ahora = datetime.now(UTC)
    return EventoClimatico(
        alerta_id=uuid.uuid4(),
        nivel=nivel,
        fenomeno="TORMENTA_FUERTE",
        barrios=["PALERMO"],
        ubicaciones=[],
        vigencia_desde=ahora - timedelta(hours=1),
        vigencia_hasta=ahora + timedelta(hours=4),
        estado=estado,
    )


def _reclamo(alerta_id: uuid.UUID | None = None) -> Reclamo:
    return Reclamo(
        ciudadano_id=str(uuid.uuid4()),
        titulo="Arbol caido",
        descripcion="Se cayo un arbol en la vereda",
        categoria=CategoriaReclamo.ARBOLADO,
        prioridad=PrioridadReclamo.ALTA,
        estado=EstadoReclamo.RECIBIDO,
        canal=CanalOrigen.APP,
        origen_clasificacion=OrigenClasificacion.CIUDADANO,
        barrio="Palermo",
        alerta_id=alerta_id,
    )


async def _recargar(session, reclamo: Reclamo) -> Reclamo:
    """Re-read through the ORM so the `selectin` relationship is populated."""
    session.expunge_all()
    return await session.get(Reclamo, reclamo.id)


@pytest.mark.asyncio
async def test_un_reclamo_bajo_alerta_activa_lo_muestra(session) -> None:
    alerta = _alerta(nivel=NivelCriticidad.ALTA)
    reclamo = _reclamo(alerta.alerta_id)
    session.add_all([alerta, reclamo])
    await session.commit()

    salida = ReclamoDetalle.model_validate(await _recargar(session, reclamo))

    assert salida.bajo_alerta_climatica is True
    assert salida.alerta_nivel is NivelCriticidad.ALTA


@pytest.mark.asyncio
async def test_con_la_alerta_finalizada_deja_de_mostrarse(session) -> None:
    # The claim keeps its alerta_id -- it is history and Analytics reads it --
    # so the mark alone would keep saying "under alert" forever. What decides is
    # the alert's state.
    alerta = _alerta(estado=EstadoEventoClimatico.FINALIZADA)
    reclamo = _reclamo(alerta.alerta_id)
    session.add_all([alerta, reclamo])
    await session.commit()

    recargado = await _recargar(session, reclamo)
    salida = ReclamoDetalle.model_validate(recargado)

    assert recargado.alerta_id == alerta.alerta_id
    assert salida.bajo_alerta_climatica is False
    assert salida.alerta_nivel is None


@pytest.mark.asyncio
async def test_un_reclamo_sin_alerta_sale_en_false(session) -> None:
    reclamo = _reclamo(None)
    session.add(reclamo)
    await session.commit()

    salida = ReclamoDetalle.model_validate(await _recargar(session, reclamo))

    assert salida.bajo_alerta_climatica is False
    assert salida.alerta_nivel is None


@pytest.mark.asyncio
async def test_una_alerta_confirmada_pero_no_activa_tambien_cuenta(session) -> None:
    # CONFIRMADA is the state an alert arrives in, before its window opens. It
    # is not FINALIZADA, so the claim is under it.
    alerta = _alerta(nivel=NivelCriticidad.CRITICA, estado=EstadoEventoClimatico.CONFIRMADA)
    reclamo = _reclamo(alerta.alerta_id)
    session.add_all([alerta, reclamo])
    await session.commit()

    salida = ReclamoDetalle.model_validate(await _recargar(session, reclamo))

    assert salida.bajo_alerta_climatica is True
    assert salida.alerta_nivel is NivelCriticidad.CRITICA


@pytest.mark.asyncio
async def test_los_seis_schemas_lo_heredan(session) -> None:
    # The fields live in CamposDerivadosMixin precisely so nobody has to
    # remember to add them to a new response schema.
    alerta = _alerta()
    reclamo = _reclamo(alerta.alerta_id)
    session.add_all([alerta, reclamo])
    await session.commit()
    recargado = await _recargar(session, reclamo)

    for schema in (ReclamoDetalle, ReclamoBandeja):
        salida = schema.model_validate(recargado)
        assert salida.bajo_alerta_climatica is True, schema.__name__
        assert salida.alerta_nivel is NivelCriticidad.ALTA, schema.__name__

    # ReclamoListado needs `es_propio`, which the endpoint adds; built the same
    # way it does.
    listado = ReclamoListado(
        **ReclamoResumen.model_validate(recargado).model_dump(), es_propio=False
    )
    assert listado.bajo_alerta_climatica is True
    assert listado.alerta_nivel is NivelCriticidad.ALTA


@pytest.mark.asyncio
async def test_el_listado_no_consulta_la_alerta_por_cada_reclamo(session, engine) -> None:
    # `selectin` loads every alert in one extra query, not one per row. Without
    # it a page of fifty claims would fire fifty queries, and the symptom would
    # be a slow listing rather than a visible error.
    from sqlalchemy import event, select

    alerta = _alerta()
    session.add(alerta)
    for _ in range(5):
        session.add(_reclamo(alerta.alerta_id))
    await session.commit()
    session.expunge_all()

    consultas: list[str] = []

    def registrar(conn, cursor, statement, *_args) -> None:
        consultas.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", registrar)
    try:
        resultado = await session.execute(select(Reclamo))
        reclamos = list(resultado.scalars().all())
        salidas = [ReclamoBandeja.model_validate(r) for r in reclamos]
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", registrar)

    assert len(salidas) == 5
    assert all(s.bajo_alerta_climatica for s in salidas)
    # One query for the claims plus one for the alerts: never one per claim.
    sobre_alertas = [q for q in consultas if "eventos_climaticos" in q]
    assert len(sobre_alertas) == 1, f"{len(sobre_alertas)} consultas a eventos_climaticos"
