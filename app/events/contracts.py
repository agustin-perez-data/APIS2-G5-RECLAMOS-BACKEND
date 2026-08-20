"""Event contracts (envelope + payloads).

The envelope follows the CloudEvents shape but uses explicit names. So we can
still integrate with modules publishing plain CloudEvents, every field also
accepts the short name (`id`, `type`, `time`, `source`).

Versioning rule: adding optional fields keeps `event_version`; removing or
renaming a field forces a major bump and dual publishing until consumers have
migrated (see `docs/adr/0003-contratos-de-eventos.md`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from app.domain.enums import CategoriaReclamo, EstadoReclamo, PrioridadReclamo

TPayload = TypeVar("TPayload", bound=BaseModel)


def _ahora() -> datetime:
    return datetime.now(UTC)


class EventEnvelope(BaseModel, Generic[TPayload]):
    """Envelope shared by every event entering or leaving the bus."""

    model_config = ConfigDict(populate_by_name=True)

    event_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        validation_alias=AliasChoices("event_id", "id", "eventId"),
    )
    event_type: str = Field(validation_alias=AliasChoices("event_type", "type", "eventType"))
    event_version: str = Field(
        default="1.0",
        validation_alias=AliasChoices("event_version", "version", "dataschema"),
    )
    occurred_at: datetime = Field(
        default_factory=_ahora,
        validation_alias=AliasChoices("occurred_at", "time", "timestamp", "occurredAt"),
    )
    source: str = Field(default="reclamos", validation_alias=AliasChoices("source", "modulo"))
    # Lets us follow an interaction that crosses several modules.
    correlation_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("correlation_id", "correlationId", "traceId"),
    )
    data: TPayload


# --- Published payloads ------------------------------------------------------
class ReclamoCreado(BaseModel):
    reclamo_id: uuid.UUID
    ciudadano_id: str
    titulo: str
    categoria: CategoriaReclamo
    prioridad: PrioridadReclamo
    estado: EstadoReclamo
    barrio: str | None = None
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    creado_at: datetime


class ReclamoClasificado(BaseModel):
    reclamo_id: uuid.UUID
    categoria: CategoriaReclamo
    prioridad: PrioridadReclamo
    confianza: float
    modelo: str
    evidencia: list[str] = Field(default_factory=list)


class ReclamoEstadoCambiado(BaseModel):
    reclamo_id: uuid.UUID
    ciudadano_id: str
    estado_anterior: EstadoReclamo
    estado_nuevo: EstadoReclamo
    motivo: str | None = None
    asignado_a: str | None = None
    cambiado_por: str
    cambiado_at: datetime


class ReclamoResuelto(BaseModel):
    reclamo_id: uuid.UUID
    ciudadano_id: str
    categoria: CategoriaReclamo
    resolucion: str | None = None
    # Metric Group 8 needs for the management dashboards.
    horas_hasta_resolucion: float
    resuelto_at: datetime


class ReclamoAdherido(BaseModel):
    reclamo_id: uuid.UUID
    ciudadano_id: str
    adhesiones_count: int
    prioridad: PrioridadReclamo
    escalado: bool


# --- Consumed payloads -------------------------------------------------------
# `extra="allow"` on purpose: if another team adds fields, the consumer must not
# blow up. Only the fields we actually depend on are declared.
class ContenedorDesbordado(BaseModel):
    model_config = ConfigDict(extra="allow")

    contenedor_id: str = Field(validation_alias=AliasChoices("contenedor_id", "contenedorId", "id"))
    nivel_llenado: float | None = Field(
        default=None, validation_alias=AliasChoices("nivel_llenado", "nivelLlenado", "nivel")
    )
    direccion: str | None = None
    barrio: str | None = None
    latitud: float | None = Field(default=None, validation_alias=AliasChoices("latitud", "lat"))
    longitud: float | None = Field(
        default=None, validation_alias=AliasChoices("longitud", "lng", "lon")
    )


class IncidenteCreado(BaseModel):
    model_config = ConfigDict(extra="allow")

    incidente_id: str = Field(validation_alias=AliasChoices("incidente_id", "incidenteId", "id"))
    tipo: str | None = None
    severidad: str | None = Field(
        default=None, validation_alias=AliasChoices("severidad", "criticidad", "nivel")
    )
    barrio: str | None = None
    latitud: float | None = Field(default=None, validation_alias=AliasChoices("latitud", "lat"))
    longitud: float | None = Field(
        default=None, validation_alias=AliasChoices("longitud", "lng", "lon")
    )


class MensajeFallido(BaseModel):
    """DLQ payload: keeps the raw message and the reason it failed."""

    topic_original: str
    error: str
    payload: dict[str, Any]


def parse_envelope(raw: dict[str, Any], data_model: type[TPayload]) -> EventEnvelope[TPayload]:
    """Validate an incoming message against the envelope + expected payload."""
    return EventEnvelope[data_model].model_validate(raw)  # type: ignore[valid-type]
