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
    IncidenteActualizado,
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


# --- EmergenciaActualizada: Avro payload used by A5 and incident closure ----
def test_la_actualizacion_lee_los_campos_de_a5_y_el_sobre() -> None:
    event_id = uuid.uuid4()
    evento = parse_envelope(
        {
            "event_id": str(event_id),
            "event_type": "emergencias.incidente.actualizado",
            "correlation_id": "corr-emergencia-1",
            "data": {
                "emergenciaId": "EMG-1",
                "estadoAnterior": "EN_CURSO",
                "estadoNuevo": "RESUELTA",
                "updatedAt": "2026-11-13T12:00:00Z",
                "resueltoAt": "2026-11-13T11:59:00Z",
                "correlationId": "corr-emergencia-1",
                "causasRelacionadas": ["VIA", "RESIDUOS"],
                "descripcionProblema": "La calzada quedo danada despues de la emergencia.",
                "barrio": "Palermo",
                "latitud": -34.589,
                "longitud": -58.431,
                "ubicacion": {
                    "barrio": "Palermo",
                    "latitud": LATITUD_CIFRADA,
                    "longitud": LONGITUD_CIFRADA,
                },
            },
        },
        IncidenteActualizado,
    )

    assert evento.event_id == event_id
    assert evento.correlation_id == "corr-emergencia-1"
    assert evento.data.incidente_id == "EMG-1"
    assert evento.data.estado_nuevo == "RESUELTA"
    assert evento.data.resuelto_at == datetime(2026, 11, 13, 11, 59, tzinfo=UTC)
    assert evento.data.correlation_id == "corr-emergencia-1"
    assert evento.data.causas_relacionadas == ["VIA", "RESIDUOS"]
    assert evento.data.descripcion_problema == "La calzada quedo danada despues de la emergencia."
    assert evento.data.barrio == "Palermo"
    assert evento.data.latitud == pytest.approx(-34.589)
    assert evento.data.longitud == pytest.approx(-58.431)
    assert evento.data.ubicacion is not None
    assert evento.data.ubicacion.latitud == LATITUD_CIFRADA


def test_la_actualizacion_usa_ubicacion_anidada_si_no_hay_coordenadas_en_raiz() -> None:
    actualizacion = IncidenteActualizado.model_validate(
        {
            "emergenciaId": "EMG-2",
            "ubicacion": {
                "barrio": "Caballito",
                "latitud": "-34.620",
                "longitud": "-58.440",
            },
        }
    )

    assert actualizacion.barrio == "Caballito"
    assert actualizacion.latitud == pytest.approx(-34.620)
    assert actualizacion.longitud == pytest.approx(-58.440)


def test_la_actualizacion_prioriza_las_coordenadas_de_la_raiz() -> None:
    actualizacion = IncidenteActualizado.model_validate(
        {
            "emergenciaId": "EMG-3",
            "barrio": "Palermo",
            "latitud": -34.589,
            "longitud": -58.431,
            "ubicacion": {"barrio": "Belgrano", "latitud": "-34.555", "longitud": "-58.459"},
        }
    )

    assert actualizacion.barrio == "Palermo"
    assert actualizacion.latitud == pytest.approx(-34.589)
    assert actualizacion.longitud == pytest.approx(-58.431)


def test_actualizacion_con_ubicacion_cifrada_no_inventa_coordenadas() -> None:
    actualizacion = IncidenteActualizado.model_validate(
        {
            "emergenciaId": "EMG-4",
            "barrio": "San Nicolas",
            "ubicacion": {"latitud": LATITUD_CIFRADA, "longitud": LONGITUD_CIFRADA},
        }
    )

    assert actualizacion.barrio == "San Nicolas"
    assert actualizacion.latitud is None
    assert actualizacion.longitud is None


def test_actualizacion_antigua_o_con_campos_nulos_sigue_siendo_legible() -> None:
    antigua = IncidenteActualizado.model_validate(
        {"emergenciaId": "EMG-5", "estadoNuevo": "RESUELTA"}
    )
    con_nulos = IncidenteActualizado.model_validate(
        {
            "emergenciaId": "EMG-6",
            "estadoNuevo": "RESUELTA",
            "causasRelacionadas": None,
            "descripcionProblema": None,
            "barrio": None,
            "latitud": None,
            "longitud": None,
            "ubicacion": None,
        }
    )

    for actualizacion in (antigua, con_nulos):
        assert actualizacion.causas_relacionadas == []
        assert actualizacion.descripcion_problema is None
        assert actualizacion.latitud is None
        assert actualizacion.longitud is None


@pytest.mark.parametrize(
    ("latitud", "longitud"),
    [(91, -58.431), (-34.589, -181), ("NaN", -58.431), ("no-es-numero", -58.431)],
)
def test_actualizacion_marca_coordenadas_invalidas_como_ausentes(latitud, longitud) -> None:
    actualizacion = IncidenteActualizado.model_validate(
        {"emergenciaId": "EMG-7", "latitud": latitud, "longitud": longitud}
    )

    if latitud in (91, "NaN", "no-es-numero"):
        assert actualizacion.latitud is None
    if longitud == -181:
        assert actualizacion.longitud is None


def test_actualizacion_no_acepta_causas_con_formato_incorrecto() -> None:
    with pytest.raises(ValidationError):
        IncidenteActualizado.model_validate({"emergenciaId": "EMG-8", "causasRelacionadas": "VIA"})


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
