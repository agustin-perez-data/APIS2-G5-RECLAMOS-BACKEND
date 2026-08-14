"""Tests for the event envelope and payload contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.domain.enums import CategoriaReclamo, EstadoReclamo, PrioridadReclamo
from app.events.contracts import (
    ContenedorDesbordado,
    EventEnvelope,
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
