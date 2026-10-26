"""The Avro schemas have to say the same thing the code actually sends.

They live in `docs/avro/` and get uploaded by hand to Group 1's catalogue, where
the gateway validates every event against them: a schema that drifts from the
code turns into events rejected in production, or worse, into a contract that
lies to the other six modules. These tests compare each schema against the real
output of `traducir()` so the drift is caught here instead.
"""

from __future__ import annotations

import json
import pathlib
import uuid
from datetime import UTC, datetime

import pytest

from app.domain.enums import (
    CategoriaReclamo,
    EstadoReclamo,
    PrioridadReclamo,
)
from app.events import topics
from app.events.contracts import (
    EventEnvelope,
    ReclamoCreado,
    ReclamoEstadoCambiado,
    ReclamoReclasificado,
)
from app.events.gateway import traducir

ESQUEMAS = pathlib.Path(__file__).resolve().parents[2] / "docs" / "avro"
AHORA = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)


def _esquema(nombre: str) -> dict:
    return json.loads((ESQUEMAS / f"{nombre}.avsc").read_text(encoding="utf-8"))


def _minimo_creado() -> EventEnvelope:
    """Only the required fields, so every optional one comes out as null."""
    return EventEnvelope(
        event_type=topics.RECLAMO_CREADO,
        data=ReclamoCreado(
            reclamo_id=uuid.uuid4(),
            ciudadano_id=str(uuid.uuid4()),
            titulo="Auto sobre la ciclovia",
            categoria=CategoriaReclamo.TRANSITO,
            prioridad=PrioridadReclamo.ALTA,
            estado=EstadoReclamo.RECIBIDO,
            creado_at=AHORA,
        ),
    )


def _minimo_actualizado() -> EventEnvelope:
    return EventEnvelope(
        event_type=topics.RECLAMO_ESTADO_CAMBIADO,
        data=ReclamoEstadoCambiado(
            reclamo_id=uuid.uuid4(),
            ciudadano_id=str(uuid.uuid4()),
            estado_anterior=EstadoReclamo.RECIBIDO,
            estado_nuevo=EstadoReclamo.ASIGNADO,
            cambiado_por="U000042",
            cambiado_at=AHORA,
        ),
    )


def _minimo_reclasificado() -> EventEnvelope:
    return EventEnvelope(
        event_type=topics.RECLAMO_RECLASIFICADO,
        data=ReclamoReclasificado(
            reclamo_id=uuid.uuid4(),
            ciudadano_id=str(uuid.uuid4()),
            categoria_anterior=CategoriaReclamo.RUIDOS,
            categoria_nueva=CategoriaReclamo.TRANSITO,
            prioridad_anterior=PrioridadReclamo.BAJA,
            prioridad_nueva=PrioridadReclamo.ALTA,
            titulo="Auto sobre la ciclovia",
            descripcion="Hay un auto arriba de la bicisenda",
            reclasificado_por="U000042",
            reclasificado_at=AHORA,
        ),
    )


CASOS = [
    (topics.RECLAMO_CREADO, _minimo_creado, "ReclamoCreado"),
    (topics.RECLAMO_ESTADO_CAMBIADO, _minimo_actualizado, "ReclamoActualizado"),
    (topics.RECLAMO_RECLASIFICADO, _minimo_reclasificado, "ReclamoReclasificado"),
]


@pytest.mark.parametrize(("topic", "armar", "nombre"), CASOS)
def test_el_esquema_declara_exactamente_los_campos_que_mandamos(topic, armar, nombre) -> None:
    esquema = _esquema(nombre)
    _, datos = traducir(topic, armar())

    declarados = {campo["name"] for campo in esquema["fields"]}
    enviados = set(datos)

    assert enviados - declarados == set(), "campos que mandamos y el esquema no declara"
    assert declarados - enviados == set(), "campos declarados que nunca mandamos"


@pytest.mark.parametrize(("topic", "armar", "nombre"), CASOS)
def test_todo_campo_que_puede_venir_nulo_esta_declarado_nullable(topic, armar, nombre) -> None:
    # Built with the optional fields left out, so whatever comes out as None is
    # a field the gateway has to accept as null or it rejects a valid event.
    esquema = _esquema(nombre)
    tipos = {campo["name"]: campo["type"] for campo in esquema["fields"]}
    _, datos = traducir(topic, armar())

    for campo, valor in datos.items():
        if valor is None:
            assert "null" in tipos[campo], f"'{campo}' puede venir nulo y el esquema no lo permite"


@pytest.mark.parametrize(("topic", "armar", "nombre"), CASOS)
def test_el_nombre_completo_coincide_con_el_del_catalogo(topic, armar, nombre) -> None:
    esquema = _esquema(nombre)
    assert f"{esquema['namespace']}.{esquema['name']}" == f"com.citypass.reclamos.{nombre}"


@pytest.mark.parametrize(("topic", "armar", "nombre"), CASOS)
def test_los_campos_opcionales_traen_default_nulo(topic, armar, nombre) -> None:
    # Avro needs the default to match the first branch of the union. Without it
    # a consumer reading an older schema cannot fill the gap.
    for campo in _esquema(nombre)["fields"]:
        if isinstance(campo["type"], list) and "null" in campo["type"]:
            assert campo.get("default", "falta") is None, f"'{campo['name']}' sin default nulo"
