"""Stage 1 of the weather alert: marking the claims already open in the area.

The cross is primary by neighbourhood and falls back to geography, so both
paths are covered here, and so is what happens to the claims that fall outside
either of them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.db.models import EventoClimatico, Reclamo
from app.domain.enums import (
    CanalOrigen,
    CategoriaReclamo,
    EstadoReclamo,
    NivelCriticidad,
    OrigenClasificacion,
    PrioridadReclamo,
)
from app.services.reclamo_service import ReclamoService

VIGENCIA_DESDE = datetime(2026, 11, 4, 18, tzinfo=UTC)
VIGENCIA_HASTA = datetime(2026, 11, 4, 23, tzinfo=UTC)


def _reclamo(
    *,
    barrio: str | None = None,
    categoria: CategoriaReclamo = CategoriaReclamo.ARBOLADO,
    prioridad: PrioridadReclamo = PrioridadReclamo.BAJA,
    latitud: float | None = None,
    longitud: float | None = None,
    estado: EstadoReclamo = EstadoReclamo.RECIBIDO,
) -> Reclamo:
    return Reclamo(
        ciudadano_id=str(uuid.uuid4()),
        titulo="Arbol caido",
        descripcion="Se cayo un arbol en la vereda",
        categoria=categoria,
        prioridad=prioridad,
        estado=estado,
        canal=CanalOrigen.APP,
        origen_clasificacion=OrigenClasificacion.CIUDADANO,
        barrio=barrio,
        latitud=latitud,
        longitud=longitud,
    )


def _alerta(
    *,
    nivel: NivelCriticidad = NivelCriticidad.ALTA,
    barrios: list[str] | None = None,
    ubicaciones: list[dict] | None = None,
) -> EventoClimatico:
    return EventoClimatico(
        alerta_id=uuid.uuid4(),
        nivel=nivel,
        fenomeno="TORMENTA_FUERTE",
        barrios=barrios if barrios is not None else ["PALERMO"],
        ubicaciones=ubicaciones or [],
        vigencia_desde=VIGENCIA_DESDE,
        vigencia_hasta=VIGENCIA_HASTA,
    )


@pytest.mark.asyncio
async def test_marca_los_reclamos_del_barrio_afectado(session, publisher) -> None:
    dentro = _reclamo(barrio="Palermo")
    fuera = _reclamo(barrio="Caballito")
    alerta = _alerta(barrios=["PALERMO"])
    session.add_all([dentro, fuera, alerta])
    await session.commit()

    resumen = await ReclamoService(session, publisher).escalar_por_alerta_climatica(alerta)

    assert resumen.marcados == 1
    assert resumen.por_barrio is True
    await session.refresh(dentro)
    await session.refresh(fuera)
    assert dentro.alerta_id == alerta.alerta_id
    assert fuera.alerta_id is None


@pytest.mark.asyncio
async def test_el_barrio_entra_aunque_este_escrito_distinto(session, publisher) -> None:
    # The whole reason barrio_codigo exists: the neighbour typed it by hand.
    con_tilde = _reclamo(barrio="  núñez ")
    alerta = _alerta(barrios=["Nuñez"])
    session.add_all([con_tilde, alerta])
    await session.commit()

    resumen = await ReclamoService(session, publisher).escalar_por_alerta_climatica(alerta)

    assert resumen.marcados == 1


@pytest.mark.asyncio
async def test_alta_sube_la_prioridad_de_las_categorias_sensibles(session, publisher) -> None:
    arbolado = _reclamo(barrio="Palermo", categoria=CategoriaReclamo.ARBOLADO)
    ruidos = _reclamo(barrio="Palermo", categoria=CategoriaReclamo.RUIDOS)
    alerta = _alerta(nivel=NivelCriticidad.ALTA, barrios=["PALERMO"])
    session.add_all([arbolado, ruidos, alerta])
    await session.commit()

    await ReclamoService(session, publisher).escalar_por_alerta_climatica(alerta)

    await session.refresh(arbolado)
    await session.refresh(ruidos)
    assert arbolado.prioridad is PrioridadReclamo.ALTA
    # A noise complaint does not get worse with a storm: it is marked and the
    # neighbour is told, but its priority is left alone.
    assert ruidos.prioridad is PrioridadReclamo.BAJA
    assert ruidos.alerta_id == alerta.alerta_id


@pytest.mark.asyncio
async def test_baja_marca_y_avisa_pero_no_mueve_prioridades(session, publisher) -> None:
    reclamo = _reclamo(barrio="Palermo", categoria=CategoriaReclamo.ARBOLADO)
    alerta = _alerta(nivel=NivelCriticidad.BAJA, barrios=["PALERMO"])
    session.add_all([reclamo, alerta])
    await session.commit()

    resumen = await ReclamoService(session, publisher).escalar_por_alerta_climatica(alerta)

    await session.refresh(reclamo)
    assert reclamo.alerta_id == alerta.alerta_id
    assert reclamo.prioridad is PrioridadReclamo.BAJA
    assert resumen.avisos_enviados == 1


@pytest.mark.asyncio
async def test_los_reclamos_cerrados_no_se_tocan(session, publisher) -> None:
    cerrado = _reclamo(barrio="Palermo", estado=EstadoReclamo.CERRADO)
    alerta = _alerta(barrios=["PALERMO"])
    session.add_all([cerrado, alerta])
    await session.commit()

    resumen = await ReclamoService(session, publisher).escalar_por_alerta_climatica(alerta)

    assert resumen.marcados == 0
    await session.refresh(cerrado)
    assert cerrado.alerta_id is None


@pytest.mark.asyncio
async def test_sin_barrios_cae_al_cruce_por_radio(session, publisher) -> None:
    # Obelisco, and a claim about 400 m away.
    cerca = _reclamo(barrio=None, latitud=-34.6040, longitud=-58.3820)
    lejos = _reclamo(barrio=None, latitud=-34.7000, longitud=-58.5000)
    alerta = _alerta(
        nivel=NivelCriticidad.BAJA,
        barrios=[],
        ubicaciones=[{"latitud": -34.6037, "longitud": -58.3816}],
    )
    session.add_all([cerca, lejos, alerta])
    await session.commit()

    resumen = await ReclamoService(session, publisher).escalar_por_alerta_climatica(alerta)

    assert resumen.por_barrio is False
    assert resumen.marcados == 1
    await session.refresh(cerca)
    await session.refresh(lejos)
    assert cerca.alerta_id == alerta.alerta_id
    assert lejos.alerta_id is None


@pytest.mark.asyncio
async def test_los_reclamos_sin_ubicacion_se_cuentan_aparte(session, publisher) -> None:
    # Neither neighbourhood nor coordinates: cannot be placed in any alert, and
    # the count is what tells Analytics how much the free text costs us.
    huerfano = _reclamo(barrio=None)
    alerta = _alerta(barrios=["PALERMO"])
    session.add_all([huerfano, alerta])
    await session.commit()

    resumen = await ReclamoService(session, publisher).escalar_por_alerta_climatica(alerta)

    assert resumen.marcados == 0
    assert resumen.sin_ubicacion == 1


@pytest.mark.asyncio
async def test_se_le_deja_un_comentario_oficial_al_vecino(session, publisher) -> None:
    reclamo = _reclamo(barrio="Palermo")
    alerta = _alerta(barrios=["PALERMO"])
    session.add_all([reclamo, alerta])
    await session.commit()
    service = ReclamoService(session, publisher)

    await service.escalar_por_alerta_climatica(alerta)

    comentarios = await service.repo.comentarios_de(reclamo.id)
    assert len(comentarios) == 1
    assert comentarios[0].es_oficial is True
    assert "alerta climatica" in comentarios[0].texto
    # No promises about timing and no "we cannot fix this".
    assert "dias" not in comentarios[0].texto.lower()
