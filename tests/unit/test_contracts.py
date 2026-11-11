"""Tests for the event envelope and payload contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.enums import (
    CategoriaReclamo,
    EstadoReclamo,
    PrioridadReclamo,
    ResultadoIntervencion,
)
from app.events.contracts import (
    ContenedorDesbordado,
    EventEnvelope,
    IncidenteCreado,
    IntervencionFinalizada,
    ReclamoCreado,
    parse_envelope,
)


def _payload_creado() -> ReclamoCreado:
    return ReclamoCreado(
        reclamo_id=uuid.uuid4(),
        ciudadano_id="u-1",
        titulo="Bache",
        categoria=CategoriaReclamo.BACHES,
        prioridad=PrioridadReclamo.MEDIA,
        estado=EstadoReclamo.RECIBIDO,
        creado_at=datetime.now(UTC),
    )


def test_el_objeto_afectado_es_opcional() -> None:
    # Optional on purpose: it must not break consumers nor bump the event version.
    assert _payload_creado().objeto_afectado is None


def test_el_envelope_completa_los_campos_automaticos() -> None:
    envelope = EventEnvelope[ReclamoCreado](
        event_type="reclamos.reclamo.creado", data=_payload_creado()
    )
    assert envelope.event_id is not None
    assert envelope.event_version == "1.0"
    assert envelope.occurred_at.tzinfo is not None


def test_el_envelope_serializa_a_json_plano() -> None:
    envelope = EventEnvelope[ReclamoCreado](
        event_type="reclamos.reclamo.creado", data=_payload_creado()
    )
    crudo = envelope.model_dump(mode="json")
    assert isinstance(crudo["event_id"], str)
    assert crudo["data"]["categoria"] == "BACHES"


def test_acepta_nombres_al_estilo_cloudevents() -> None:
    # Group 1 may publish plain CloudEvents; the aliases keep us compatible.
    crudo = {
        "id": str(uuid.uuid4()),
        "type": "residuos.contenedor.desbordado",
        "time": datetime.now(UTC).isoformat(),
        "source": "residuos",
        "data": {"contenedor_id": "CT-1"},
    }
    envelope = parse_envelope(crudo, ContenedorDesbordado)
    assert envelope.event_type == "residuos.contenedor.desbordado"
    assert envelope.data.contenedor_id == "CT-1"


def test_los_payloads_entrantes_toleran_campos_nuevos() -> None:
    # Another team adding a field must never break our consumer.
    envelope = parse_envelope(
        {
            "event_id": str(uuid.uuid4()),
            "event_type": "residuos.contenedor.desbordado",
            "data": {"contenedorId": "CT-9", "nivel": 99, "lat": -34.6, "campoNuevo": "x"},
        },
        ContenedorDesbordado,
    )
    assert envelope.data.contenedor_id == "CT-9"
    assert envelope.data.nivel_llenado == 99
    assert envelope.data.latitud == -34.6


def test_falta_el_campo_clave_del_payload() -> None:
    with pytest.raises(ValidationError):
        parse_envelope(
            {"event_type": "residuos.contenedor.desbordado", "data": {"nivel": 10}},
            ContenedorDesbordado,
        )


# How Emergencies sends the position since 6/11: base64 ciphertext we cannot read.
LATITUD_CIFRADA = "RUxDAQExuIWL05EIEbZ+pYcyRW/K80OxpZXy4Qcz56ETZxfmAL0vlgcQeUjGZq4ZEP+PEg=="
LONGITUD_CIFRADA = "RUxDAQExgnptTMas+gjNvow+FKmMMYGk8p9W9PO+Ca4YjRqnMcCsz39YUHSsdYhSivnvkA=="


# --- What other teams actually registered in the catalogue --------------------
def test_el_incidente_lee_la_ubicacion_anidada() -> None:
    # The schema Emergencies registered nests the location and types the
    # coordinates as strings; the contract they had described to us had the
    # three loose. Reading only the loose ones escalates nothing and logs a
    # success, which is the worst shape a bug can take.
    incidente = IncidenteCreado.model_validate(
        {
            "emergenciaId": "e-1",
            "categoria": "CHOQUE",
            "afectaCirculacion": True,
            "ubicacion": {"barrio": "Palermo", "latitud": "-34.5889", "longitud": "-58.4306"},
        }
    )

    assert incidente.barrio == "Palermo"
    assert incidente.latitud == pytest.approx(-34.5889)
    assert incidente.longitud == pytest.approx(-58.4306)


def test_si_el_incidente_trae_las_dos_formas_gana_la_de_arriba() -> None:
    incidente = IncidenteCreado.model_validate(
        {
            "emergenciaId": "e-2",
            "barrio": "Caballito",
            "ubicacion": {"barrio": "Palermo"},
        }
    )

    assert incidente.barrio == "Caballito"


def test_el_incidente_sin_ubicacion_sigue_andando() -> None:
    incidente = IncidenteCreado.model_validate({"emergenciaId": "e-3", "barrio": "Flores"})

    assert incidente.barrio == "Flores"
    assert incidente.latitud is None


def test_las_coordenadas_cifradas_cuentan_como_ausentes() -> None:
    # Since 6/11 Emergencies encrypts the position. Rejecting the event over it
    # was a 500 on every delivery; the neighbourhood still travels in clear.
    incidente = IncidenteCreado.model_validate(
        {
            "emergenciaId": "e-4",
            "barrio": "SAN NICOLAS",
            "ubicacion": {
                "barrio": "SAN NICOLAS",
                "latitud": LATITUD_CIFRADA,
                "longitud": LONGITUD_CIFRADA,
            },
        }
    )

    assert incidente.barrio == "SAN NICOLAS"
    assert incidente.latitud is None
    assert incidente.longitud is None


@pytest.mark.parametrize(
    ("enviado", "esperado"),
    [
        ("RESUELTO", ResultadoIntervencion.RESUELTO),
        ("completado", ResultadoIntervencion.RESUELTO),
        ("  Finalizada  ", ResultadoIntervencion.RESUELTO),
        ("RECHAZADO", ResultadoIntervencion.RECHAZADO),
        ("NO_CORRESPONDE", ResultadoIntervencion.RECHAZADO),
    ],
)
def test_el_resultado_de_la_intervencion_tolera_sinonimos(
    enviado: str, esperado: ResultadoIntervencion
) -> None:
    # Their registered schema types `resultado` as a bare string with no
    # documented values. A wording we reject sends the message to the DLQ and
    # the claim never closes, with nothing visible on their side.
    intervencion = IntervencionFinalizada.model_validate(
        {"reclamoId": str(uuid.uuid4()), "resultado": enviado}
    )

    assert intervencion.resultado is esperado


def test_un_resultado_desconocido_sigue_fallando() -> None:
    # On purpose: guessing between "fixed" and "not our job" is what tells the
    # neighbour a lie. Better the DLQ, which is findable.
    with pytest.raises(ValidationError):
        IntervencionFinalizada.model_validate(
            {"reclamoId": str(uuid.uuid4()), "resultado": "EN_CURSO"}
        )
