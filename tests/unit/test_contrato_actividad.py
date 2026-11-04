"""The `ActividadCreada` contract accepts both versions of Public Spaces' payload."""

from __future__ import annotations

from datetime import UTC, datetime

from app.events.contracts import ActividadCreada


def test_lee_las_fechas_en_milisegundos_como_utc() -> None:
    datos = ActividadCreada.model_validate(
        {
            "actividadId": "a-1",
            "titulo": "Feria",
            "capacidad": 1500,
            "fechaHoraInicio": 1793545200000,
            "fechaHoraFinalizacion": 1793563200000,
            "ubicacion": {"lat": -34.6, "lng": -58.4},
        }
    )
    assert datos.inicio == datetime(2026, 11, 1, 15, 0, tzinfo=UTC)
    assert datos.fin == datetime(2026, 11, 1, 20, 0, tzinfo=UTC)
    assert (datos.ubicacion.lat, datos.ubicacion.lng) == (-34.6, -58.4)


def test_arma_la_ubicacion_con_coordenadas_sueltas() -> None:
    datos = ActividadCreada.model_validate(
        {
            "communityEventId": "a-2",
            "title": "Recital",
            "capacity": 3000,
            "endDate": "2026-11-01T23:00:00Z",
            "latitude": -34.59,
            "longitude": -58.38,
        }
    )
    assert datos.actividad_id == "a-2"
    assert datos.capacidad == 3000
    assert (datos.ubicacion.lat, datos.ubicacion.lng) == (-34.59, -58.38)


def test_sin_coordenadas_la_ubicacion_queda_vacia() -> None:
    datos = ActividadCreada.model_validate(
        {"actividadId": "a-3", "titulo": "Feria", "fechaHoraFinalizacion": 1793570400000}
    )
    assert datos.ubicacion is None
    assert datos.inicio is None


def test_los_campos_que_no_usamos_no_molestan() -> None:
    datos = ActividadCreada.model_validate(
        {
            "actividadId": "a-4",
            "titulo": "Feria",
            "fechaHoraFinalizacion": 1793570400000,
            "actorSub": "U000042",
            "algoNuevo": {"x": 1},
        }
    )
    assert datos.actividad_id == "a-4"
