"""A5 business rules, independent of the EmergenciaActualizada handler."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.domain.enums import USUARIO_SISTEMA, PrioridadReclamo
from app.events.contracts import EventEnvelope, IncidenteActualizado
from app.services.emergencia_via_service import (
    TITULO_RECLAMO_VIAL,
    crear_reclamo_por_emergencia_vial,
)


def _evento(**cambios) -> IncidenteActualizado:
    datos = {
        "emergenciaId": "9cf9ab58-0d3b-448b-a401-68f2a34e49ff",
        "estadoNuevo": "RESUELTA",
        "causasRelacionadas": ["VIA"],
        "descripcionProblema": "El asfalto quedo danado despues de retirar los vehiculos.",
        "barrio": "Palermo",
        "latitud": -34.589,
        "longitud": -58.431,
        "correlationId": "corr-emergencia-1",
    }
    datos.update(cambios)
    return IncidenteActualizado.model_validate(datos)


def _service(resultado=None):
    return SimpleNamespace(
        crear_desde_evento=AsyncMock(return_value=resultado),
        session=SimpleNamespace(rollback=AsyncMock()),
        repo=SimpleNamespace(obtener_por_evento_origen=AsyncMock()),
    )


def _error_integridad_postgres(
    codigo: str = "23505", restriccion: str = "ix_reclamos_evento_origen_id"
) -> IntegrityError:
    # SQLAlchemy wraps asyncpg's structured error in an adapted DBAPI error.
    original = Exception("error de PostgreSQL")
    original.sqlstate = codigo
    original.constraint_name = restriccion
    adaptado = Exception("error adaptado por SQLAlchemy")
    adaptado.sqlstate = codigo
    adaptado.orig = original
    return IntegrityError("INSERT INTO reclamos", {}, adaptado)


@pytest.mark.asyncio
async def test_crea_con_titulo_fijo_autor_sistema_y_clasificacion_existente() -> None:
    reclamo = object()
    service = _service(reclamo)

    creado = await crear_reclamo_por_emergencia_vial(_evento(), service)

    assert creado is reclamo
    (datos,), opciones = service.crear_desde_evento.call_args
    assert datos.titulo == TITULO_RECLAMO_VIAL
    assert datos.descripcion == "El asfalto quedo danado despues de retirar los vehiculos."
    assert datos.barrio == "Palermo"
    assert datos.latitud == -34.589
    assert datos.longitud == -58.431
    assert datos.categoria is None
    assert datos.prioridad is None
    assert opciones == {
        "evento_id": "emergencia:9cf9ab58-0d3b-448b-a401-68f2a34e49ff",
        "correlation_id": "corr-emergencia-1",
        "ciudadano_id": USUARIO_SISTEMA,
        "prioridad_minima": PrioridadReclamo.ALTA,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cambios",
    [
        {"estadoNuevo": "EN_CURSO"},
        {"estadoNuevo": "CERRADA"},
        {"estadoNuevo": "resuelta"},
        {"estadoNuevo": None},
        {"causasRelacionadas": ["RESIDUOS"]},
        {"causasRelacionadas": ["via"]},
        {"causasRelacionadas": []},
        {"causasRelacionadas": None},
    ],
)
async def test_solo_resuelta_con_via_activa_a5(cambios) -> None:
    service = _service()

    assert await crear_reclamo_por_emergencia_vial(_evento(**cambios), service) is None
    service.crear_desde_evento.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cambios",
    [
        {"latitud": None},
        {"longitud": None},
        {"latitud": 91},
        {"longitud": -181},
        {"latitud": "cifrada"},
        {"latitud": "NaN"},
    ],
)
async def test_sin_ambas_coordenadas_validas_no_crea(cambios) -> None:
    service = _service()

    with pytest.raises(ValueError, match="latitud y longitud validas"):
        await crear_reclamo_por_emergencia_vial(_evento(**cambios), service)
    service.crear_desde_evento.assert_not_awaited()


@pytest.mark.asyncio
async def test_barrio_sin_coordenadas_no_basta() -> None:
    service = _service()

    with pytest.raises(ValueError, match="latitud y longitud validas"):
        await crear_reclamo_por_emergencia_vial(
            _evento(latitud=None, longitud=None, barrio="Palermo"), service
        )
    service.crear_desde_evento.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordenadas_validas_sin_barrio_si_bastan() -> None:
    service = _service(object())

    await crear_reclamo_por_emergencia_vial(_evento(barrio=None), service)

    (datos,), _ = service.crear_desde_evento.call_args
    assert datos.barrio is None
    assert datos.latitud == -34.589
    assert datos.longitud == -58.431


@pytest.mark.asyncio
@pytest.mark.parametrize("descripcion", [None, "", "   "])
async def test_descripcion_ausente_o_vacia_no_crea(descripcion) -> None:
    service = _service()

    with pytest.raises(ValueError, match="descripcionProblema"):
        await crear_reclamo_por_emergencia_vial(_evento(descripcionProblema=descripcion), service)
    service.crear_desde_evento.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("descripcion", ["corta", "x" * 5001])
async def test_descripcion_fuera_de_los_limites_del_reclamo_no_crea(descripcion) -> None:
    service = _service()

    with pytest.raises(ValidationError):
        await crear_reclamo_por_emergencia_vial(_evento(descripcionProblema=descripcion), service)
    service.crear_desde_evento.assert_not_awaited()


@pytest.mark.asyncio
async def test_reentregas_con_distinto_event_id_usan_la_misma_clave() -> None:
    service = _service()
    service.crear_desde_evento.side_effect = [object(), None]
    primero_evento = EventEnvelope[IncidenteActualizado](
        event_type="emergencias.incidente.actualizado", data=_evento()
    )
    segundo_evento = EventEnvelope[IncidenteActualizado](
        event_type="emergencias.incidente.actualizado", data=_evento()
    )

    primero = await crear_reclamo_por_emergencia_vial(primero_evento.data, service)
    segundo = await crear_reclamo_por_emergencia_vial(segundo_evento.data, service)

    assert primero_evento.event_id != segundo_evento.event_id
    assert primero is not None
    assert segundo is None
    claves = [llamada.kwargs["evento_id"] for llamada in service.crear_desde_evento.call_args_list]
    assert claves == [
        "emergencia:9cf9ab58-0d3b-448b-a401-68f2a34e49ff",
        "emergencia:9cf9ab58-0d3b-448b-a401-68f2a34e49ff",
    ]


@pytest.mark.asyncio
async def test_entregas_concurrentes_tratan_la_colision_unica_como_duplicado() -> None:
    llegadas = 0
    ambas_llegaron = asyncio.Event()
    guardado = None

    async def crear_en_carrera(*_args, **_kwargs):
        nonlocal llegadas, guardado
        llegadas += 1
        if llegadas == 2:
            ambas_llegaron.set()
        await ambas_llegaron.wait()
        if guardado is None:
            guardado = object()
            return guardado
        raise _error_integridad_postgres()

    primero = _service()
    segundo = _service()
    for service in (primero, segundo):
        service.crear_desde_evento.side_effect = crear_en_carrera
        service.repo.obtener_por_evento_origen.side_effect = lambda _clave: guardado

    resultados = await asyncio.gather(
        crear_reclamo_por_emergencia_vial(_evento(), primero),
        crear_reclamo_por_emergencia_vial(_evento(), segundo),
    )

    assert resultados.count(guardado) == 1
    assert resultados.count(None) == 1
    assert primero.session.rollback.await_count + segundo.session.rollback.await_count == 1
    assert (
        primero.repo.obtener_por_evento_origen.await_count
        + segundo.repo.obtener_por_evento_origen.await_count
        == 1
    )


@pytest.mark.asyncio
async def test_un_error_de_integridad_sin_reclamo_existente_se_propaga() -> None:
    service = _service()
    service.crear_desde_evento.side_effect = _error_integridad_postgres()
    service.repo.obtener_por_evento_origen.return_value = None

    with pytest.raises(IntegrityError):
        await crear_reclamo_por_emergencia_vial(_evento(), service)

    service.session.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("codigo", "restriccion"),
    [
        ("23505", "ix_reclamos_ticket_externo"),
        ("23502", "reclamos_ciudadano_id_not_null"),
        ("23505", "otra_restriccion_unica"),
    ],
)
async def test_otro_error_de_integridad_se_propaga_aunque_exista_el_origen(
    codigo: str, restriccion: str
) -> None:
    service = _service()
    error = _error_integridad_postgres(codigo, restriccion)
    service.crear_desde_evento.side_effect = error
    service.repo.obtener_por_evento_origen.return_value = object()

    with pytest.raises(IntegrityError) as capturado:
        await crear_reclamo_por_emergencia_vial(_evento(), service)

    assert capturado.value is error
    service.session.rollback.assert_awaited_once()
    service.repo.obtener_por_evento_origen.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_trunca_el_identificador_de_la_emergencia() -> None:
    service = _service()

    with pytest.raises(ValueError, match="emergenciaId supera"):
        await crear_reclamo_por_emergencia_vial(_evento(emergenciaId="e" * 54), service)
    service.crear_desde_evento.assert_not_awaited()
