"""Road incidents from Emergencies, and the claims they cause (ADR 0017).

Analytics counts "claims associated with a road incident" from `causaTipo`. For
that to mean anything the incident has to outlive the event that announced it
-- before this we escalated the area's claims and kept no trace -- and it has to
stop being open when the street is cleared.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import (
    USUARIO_SISTEMA,
    CanalOrigen,
    CategoriaReclamo,
    CausaTipo,
    OrigenClasificacion,
    PrioridadReclamo,
)
from app.events import topics
from app.events.handlers import manejar_incidente_actualizado, manejar_incidente_creado
from app.schemas.reclamo import ReclamoCrear
from app.services.emergencia_via_service import TITULO_RECLAMO_VIAL
from app.services.reclamo_service import ReclamoService

OBELISCO = (-34.6037, -58.3816)


def _evento(tipo: str, data: dict) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": tipo,
        "occurred_at": datetime.now(UTC).isoformat(),
        "source": "emergencias",
        "data": data,
    }


def evento_creado(**overrides) -> dict:
    data = {
        "emergenciaId": "EMG-1",
        "categoria": "CHOQUE",
        "prioridad": "alta",
        "afectaCirculacion": True,
        # The shape their catalogue schema actually has: nested, strings.
        "ubicacion": {"latitud": str(OBELISCO[0]), "longitud": str(OBELISCO[1])},
    }
    data.update(overrides)
    return _evento(topics.EMERGENCIAS_INCIDENTE_CREADO, data)


def evento_cerrado(estado: str = "RESUELTA", **overrides) -> dict:
    data = {"emergenciaId": "EMG-1", "estadoNuevo": estado, "estadoAnterior": "EN_CURSO"}
    data.update(overrides)
    return _evento(topics.EMERGENCIAS_INCIDENTE_ACTUALIZADO, data)


def evento_a5(**overrides) -> dict:
    data = {
        "causasRelacionadas": ["VIA"],
        "descripcionProblema": "Quedo un pozo profundo en la calzada luego del accidente.",
        "barrio": "San Nicolas",
        "latitud": OBELISCO[0],
        "longitud": OBELISCO[1],
        "correlationId": "corr-emergencia-a5",
    }
    data.update(overrides)
    return evento_cerrado(**data)


def reclamo_en(lat: float, lon: float) -> ReclamoCrear:
    return ReclamoCrear(
        titulo="Pozo en la calzada",
        descripcion="Quedo un pozo grande en el carril del medio y no se puede pasar",
        categoria=CategoriaReclamo.BACHES,
        latitud=lat,
        longitud=lon,
    )


def causa_publicada(publisher) -> tuple[str | None, CausaTipo | None]:
    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[-1]
    return creado.data.causa_id, creado.data.causa_tipo


# --- Keeping the incident -----------------------------------------------------
@pytest.mark.asyncio
async def test_un_incidente_que_corta_la_calle_se_guarda(service: ReclamoService) -> None:
    await manejar_incidente_creado(evento_creado(), service)

    assert await service.incidentes.repo.obtener_por_origen("EMG-1") is not None


@pytest.mark.asyncio
async def test_un_incidente_que_no_corta_la_calle_no_se_guarda(service: ReclamoService) -> None:
    # A medical emergency concerns one person, not the street.
    await manejar_incidente_creado(evento_creado(afectaCirculacion=False), service)

    assert await service.incidentes.repo.obtener_por_origen("EMG-1") is None


@pytest.mark.asyncio
async def test_un_incidente_sin_coordenadas_no_se_guarda(service: ReclamoService) -> None:
    # It still escalates the neighbourhood's claims; what it cannot do is be the
    # cause of anything, because there is no "near" without a position.
    await manejar_incidente_creado(evento_creado(ubicacion=None, barrio="Palermo"), service)

    assert await service.incidentes.repo.obtener_por_origen("EMG-1") is None


@pytest.mark.asyncio
async def test_el_reenvio_del_mismo_incidente_no_lo_duplica(service: ReclamoService) -> None:
    # The gateway is at-least-once.
    await manejar_incidente_creado(evento_creado(), service)
    await manejar_incidente_creado(evento_creado(), service)

    assert await service.incidentes.repo.obtener_por_origen("EMG-1") is not None


# --- The claim it causes ------------------------------------------------------
@pytest.mark.asyncio
async def test_un_reclamo_al_lado_sale_con_el_incidente_como_causa(
    service: ReclamoService, publisher
) -> None:
    await manejar_incidente_creado(evento_creado(), service)

    await service.crear(reclamo_en(*OBELISCO), str(uuid.uuid4()))

    causa_id, causa_tipo = causa_publicada(publisher)
    assert causa_tipo is CausaTipo.INCIDENTE_VIAL
    assert causa_id == "EMG-1"


@pytest.mark.asyncio
async def test_un_reclamo_lejos_no_lo_tiene_como_causa(service: ReclamoService, publisher) -> None:
    await manejar_incidente_creado(evento_creado(), service)

    # ~5 km away, well outside the 300 m cause radius.
    await service.crear(reclamo_en(-34.6480, -58.3900), str(uuid.uuid4()))

    _, causa_tipo = causa_publicada(publisher)
    assert causa_tipo is None


@pytest.mark.asyncio
async def test_despues_del_cierre_deja_de_ser_causa(service: ReclamoService, publisher) -> None:
    await manejar_incidente_creado(evento_creado(), service)
    await manejar_incidente_actualizado(evento_cerrado(), service)

    await service.crear(reclamo_en(*OBELISCO), str(uuid.uuid4()))

    _, causa_tipo = causa_publicada(publisher)
    assert causa_tipo is None


@pytest.mark.asyncio
async def test_un_estado_que_no_es_final_lo_deja_abierto(
    service: ReclamoService, publisher
) -> None:
    # Closing on a word we are unsure about would silently stop relating claims
    # caused by a street that is still cut.
    await manejar_incidente_creado(evento_creado(), service)
    await manejar_incidente_actualizado(evento_cerrado("EN_PROCESO"), service)

    await service.crear(reclamo_en(*OBELISCO), str(uuid.uuid4()))

    _, causa_tipo = causa_publicada(publisher)
    assert causa_tipo is CausaTipo.INCIDENTE_VIAL


# --- A5 and incident closure on the same update ------------------------------
@pytest.mark.asyncio
async def test_a5_crea_reclamo_sin_incidente_interno_previo(
    service: ReclamoService, publisher, session
) -> None:
    await manejar_incidente_actualizado(evento_a5(), service)

    session.expunge_all()
    reclamo = await service.repo.obtener_por_evento_origen("emergencia:EMG-1")
    assert reclamo is not None
    assert reclamo.ciudadano_id == USUARIO_SISTEMA
    assert reclamo.titulo == TITULO_RECLAMO_VIAL
    assert reclamo.descripcion == "Quedo un pozo profundo en la calzada luego del accidente."
    assert reclamo.barrio == "San Nicolas"
    assert (reclamo.latitud, reclamo.longitud) == OBELISCO
    assert reclamo.canal is CanalOrigen.EVENTO
    assert reclamo.origen_clasificacion is OrigenClasificacion.MODELO
    assert reclamo.prioridad in {PrioridadReclamo.ALTA, PrioridadReclamo.CRITICA}
    assert reclamo.incidente_id is None
    assert reclamo.correlation_id == "corr-emergencia-a5"
    assert publisher.topics == [topics.RECLAMO_CREADO, topics.RECLAMO_CLASIFICADO]
    publicado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert publicado.data.reclamo_id == reclamo.id
    assert publicado.data.prioridad is reclamo.prioridad


@pytest.mark.asyncio
async def test_a5_cierra_primero_el_incidente_y_luego_crea_el_reclamo(
    service: ReclamoService, publisher, session
) -> None:
    await manejar_incidente_creado(evento_creado(), service)
    await manejar_incidente_actualizado(evento_a5(), service)

    session.expunge_all()
    incidente = await service.incidentes.repo.obtener_por_origen("EMG-1")
    reclamo = await service.repo.obtener_por_evento_origen("emergencia:EMG-1")
    assert incidente is not None and incidente.fin is not None
    assert reclamo is not None
    assert reclamo.incidente_id is None
    assert len(publisher.eventos_de(topics.RECLAMO_CREADO)) == 1


@pytest.mark.asyncio
async def test_a5_reentregado_con_otro_event_id_no_duplica(
    service: ReclamoService, publisher, session
) -> None:
    primero = evento_a5()
    segundo = evento_a5()
    assert primero["event_id"] != segundo["event_id"]

    await manejar_incidente_actualizado(primero, service)
    await manejar_incidente_actualizado(segundo, service)

    session.expunge_all()
    assert await service.repo.obtener_por_evento_origen("emergencia:EMG-1") is not None
    assert len(publisher.eventos_de(topics.RECLAMO_CREADO)) == 1
    assert len(publisher.eventos_de(topics.RECLAMO_CLASIFICADO)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "evento",
    [
        evento_cerrado("CERRADA", causasRelacionadas=["VIA"]),
        evento_cerrado("RESUELTA", causasRelacionadas=["RESIDUOS"]),
    ],
)
async def test_estado_final_o_causa_sin_a5_solo_cierra_incidente(
    service: ReclamoService, publisher, evento: dict
) -> None:
    await manejar_incidente_creado(evento_creado(), service)

    await manejar_incidente_actualizado(evento, service)

    incidente = await service.incidentes.repo.obtener_por_origen("EMG-1")
    assert incidente is not None and incidente.fin is not None
    assert await service.repo.obtener_por_evento_origen("emergencia:EMG-1") is None
    assert publisher.eventos_de(topics.RECLAMO_CREADO) == []


@pytest.mark.asyncio
async def test_a5_sin_coordenadas_no_crea_pero_cierra_incidente(service: ReclamoService) -> None:
    await manejar_incidente_creado(evento_creado(), service)

    with pytest.raises(ValueError, match="latitud y longitud validas"):
        await manejar_incidente_actualizado(evento_a5(latitud=None, longitud=None), service)

    incidente = await service.incidentes.repo.obtener_por_origen("EMG-1")
    assert incidente is not None and incidente.fin is not None
    assert await service.repo.obtener_por_evento_origen("emergencia:EMG-1") is None


@pytest.mark.asyncio
async def test_un_incidente_que_nadie_cerro_caduca_solo(
    service: ReclamoService, publisher, session
) -> None:
    # The safety net: a lost closing event must not leave a street "blocked"
    # forever. `incidente_vigencia_horas` is 24 by default.
    await manejar_incidente_creado(evento_creado(), service)
    incidente = await service.incidentes.repo.obtener_por_origen("EMG-1")
    incidente.inicio = datetime.now(UTC) - timedelta(hours=30)
    await session.commit()

    await service.crear(reclamo_en(*OBELISCO), str(uuid.uuid4()))

    _, causa_tipo = causa_publicada(publisher)
    assert causa_tipo is None


@pytest.mark.asyncio
async def test_con_alerta_climatica_gana_la_alerta(
    service: ReclamoService, publisher, session
) -> None:
    # The precedence of ADR 0016/0017: the storm explains why the claim exists;
    # the incident is one cut street inside it.
    from app.db.models import EventoClimatico
    from app.domain.enums import EstadoEventoClimatico, NivelCriticidad

    ahora = datetime.now(UTC)
    alerta = EventoClimatico(
        alerta_id=uuid.uuid4(),
        nivel=NivelCriticidad.ALTA,
        fenomeno="TORMENTA_FUERTE",
        barrios=["PALERMO"],
        ubicaciones=[],
        vigencia_desde=ahora - timedelta(hours=1),
        vigencia_hasta=ahora + timedelta(hours=4),
        estado=EstadoEventoClimatico.ACTIVA,
    )
    session.add(alerta)
    await session.commit()
    await manejar_incidente_creado(evento_creado(), service)

    datos = reclamo_en(*OBELISCO)
    datos.barrio = "Palermo"
    await service.crear(datos, str(uuid.uuid4()))

    causa_id, causa_tipo = causa_publicada(publisher)
    assert causa_tipo is CausaTipo.EVENTO_CLIMATICO
    assert causa_id == str(alerta.alerta_id)


@pytest.mark.asyncio
async def test_el_incidente_viaja_al_gateway_como_causa(service: ReclamoService, publisher) -> None:
    from app.events.gateway import traducir

    await manejar_incidente_creado(evento_creado(), service)
    await service.crear(reclamo_en(*OBELISCO), str(uuid.uuid4()))

    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[-1]
    _, datos = traducir(topics.RECLAMO_CREADO, creado)
    assert datos["causaTipo"] == "INCIDENTE_VIAL"
    assert datos["causaId"] == "EMG-1"


@pytest.mark.asyncio
async def test_el_incidente_guardado_conserva_lo_que_vino(service: ReclamoService) -> None:
    await manejar_incidente_creado(evento_creado(barrio="Centro"), service)

    incidente = await service.incidentes.repo.obtener_por_origen("EMG-1")
    assert incidente is not None
    assert incidente.tipo == "CHOQUE"
    assert incidente.barrio == "Centro"
    assert incidente.latitud == pytest.approx(OBELISCO[0])
    assert incidente.fin is None
