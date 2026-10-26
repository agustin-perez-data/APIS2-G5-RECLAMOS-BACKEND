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

from app.domain.enums import (
    CategoriaReclamo,
    EstadoReclamo,
    ObjetoAfectado,
    PrioridadReclamo,
    ResultadoIntervencion,
)

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
    # Optional addition: consumers that ignore it keep working, so no version bump.
    objeto_afectado: ObjetoAfectado | None = None
    prioridad: PrioridadReclamo
    estado: EstadoReclamo
    barrio: str | None = None
    direccion: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    creado_at: datetime
    # Added for CU-INT-01 (optional, so the contract version stays at 1.0).
    # Analytics needs them in its silver layer.
    canal: str | None = None
    descripcion: str | None = None
    origen_clasificacion: str | None = None
    confianza_clasificacion: float | None = None


class ReclamoClasificado(BaseModel):
    reclamo_id: uuid.UUID
    categoria: CategoriaReclamo
    objeto_afectado: ObjetoAfectado | None = None
    prioridad: PrioridadReclamo
    confianza: float
    modelo: str
    evidencia: list[str] = Field(default_factory=list)


class ReclamoReclasificado(BaseModel):
    """An operator corrected the classification of a claim.

    Separate from `ReclamoClasificado`, which describes what the model decided
    and carries its confidence, name and evidence. A human correction has none
    of that, and consumers need the previous value to undo what they did with
    the old one: Waste frees a container when a claim stops being TRANSITO.
    """

    reclamo_id: uuid.UUID
    ciudadano_id: str
    categoria_anterior: CategoriaReclamo
    categoria_nueva: CategoriaReclamo
    prioridad_anterior: PrioridadReclamo
    prioridad_nueva: PrioridadReclamo
    objeto_afectado_anterior: ObjetoAfectado | None = None
    objeto_afectado_nuevo: ObjetoAfectado | None = None
    titulo: str
    descripcion: str
    barrio: str | None = None
    latitud: float | None = None
    longitud: float | None = None
    reclasificado_por: str
    reclasificado_at: datetime


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
    objeto_afectado: ObjetoAfectado | None = None
    resolucion: str | None = None
    # Metric Group 8 needs for the management dashboards.
    horas_hasta_resolucion: float
    resuelto_at: datetime


class ReclamoComentarioCreado(BaseModel):
    # No text on purpose: it is free-form citizen content. A consumer that needs
    # it asks for the comment by id.
    comentario_id: uuid.UUID
    reclamo_id: uuid.UUID
    ciudadano_id: str
    autor_id: str
    autor_nombre: str | None = None
    es_oficial: bool
    created_at: datetime


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
    # Waste publishes the zone where the container sits as `zona`.
    barrio: str | None = Field(default=None, validation_alias=AliasChoices("barrio", "zona"))
    latitud: float | None = Field(default=None, validation_alias=AliasChoices("latitud", "lat"))
    longitud: float | None = Field(
        default=None, validation_alias=AliasChoices("longitud", "lng", "lon")
    )


class IncidenteCreado(BaseModel):
    model_config = ConfigDict(extra="allow")

    incidente_id: str = Field(
        validation_alias=AliasChoices("incidente_id", "incidenteId", "emergenciaId", "id")
    )
    tipo: str | None = Field(default=None, validation_alias=AliasChoices("tipo", "categoria"))
    severidad: str | None = Field(
        default=None, validation_alias=AliasChoices("severidad", "criticidad", "nivel", "prioridad")
    )
    barrio: str | None = None
    # CU-INT-01: Emergencies marks whether the incident cuts circulation.
    afecta_circulacion: bool | None = Field(
        default=None, validation_alias=AliasChoices("afecta_circulacion", "afectaCirculacion")
    )
    latitud: float | None = Field(default=None, validation_alias=AliasChoices("latitud", "lat"))
    longitud: float | None = Field(
        default=None, validation_alias=AliasChoices("longitud", "lng", "lon")
    )


class IntervencionFinalizada(BaseModel):
    """`com.citypass.espacios.IntervencionFinalizada` (CU-INT-01).

    Public Spaces closing the job in the street. `resultado` is what tells a
    real fix apart from a claim they did not take: both end the claim, but the
    neighbour reads something different.
    """

    model_config = ConfigDict(extra="allow")

    reclamo_id: uuid.UUID = Field(validation_alias=AliasChoices("reclamo_id", "reclamoId"))
    resultado: ResultadoIntervencion
    # Operational detail of their domain: we store none of it, but it travels so
    # Analytics can measure how long the intervention took.
    solicitado_at: int | None = Field(
        default=None, validation_alias=AliasChoices("solicitado_at", "solicitadoAt")
    )
    resuelto_at: int | None = Field(
        default=None, validation_alias=AliasChoices("resuelto_at", "resueltoAt")
    )


class EventoCulturalPublicado(BaseModel):
    """`com.citypass.espacios.EventoComunitarioPublicado` (CU-INT-01)."""

    model_config = ConfigDict(extra="allow")

    evento_id: str = Field(validation_alias=AliasChoices("evento_id", "eventoId"))
    titulo: str
    # ACTIVE, ACTIVE_FULL or CANCELLED. A cancelled event concentrates nobody.
    estado: str | None = None
    zona: str | None = None
    inicio: datetime
    inscriptos: int = 0
    cupo_maximo: int | None = Field(
        default=None, validation_alias=AliasChoices("cupo_maximo", "cupoMaximo")
    )


class MensajeFallido(BaseModel):
    """DLQ payload: keeps the raw message and the reason it failed."""

    topic_original: str
    error: str
    payload: dict[str, Any]


def parse_envelope(raw: dict[str, Any], data_model: type[TPayload]) -> EventEnvelope[TPayload]:
    """Validate an incoming message against the envelope + expected payload."""
    return EventEnvelope[data_model].model_validate(raw)  # type: ignore[valid-type]
