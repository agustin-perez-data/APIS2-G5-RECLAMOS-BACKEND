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

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.enums import (
    CategoriaReclamo,
    CausaTipo,
    EstadoReclamo,
    NivelCriticidad,
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
    # Reserved for the weather alert mode (squad 3). They travel null until that
    # feature exists: the schemas get registered in Group 1's catalogue once, and
    # declaring both now is far cheaper than coordinating a second registration.
    alerta_id: uuid.UUID | None = None
    # What originated the claim, for Analytics (ADR 0016); null = normal flow.
    # The activity also travels on its own: a claim has a single cause and a
    # weather alert outranks the activity, so the cause alone would hide it.
    # It is Public Spaces' id, the one Analytics joins with ActividadCreada.
    causa_id: str | None = None
    causa_tipo: CausaTipo | None = None
    actividad_origen_id: str | None = None


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
    # Reserved for the weather alert mode (squad 3). They travel null until that
    # feature exists: the schemas get registered in Group 1's catalogue once, and
    # declaring both now is far cheaper than coordinating a second registration.
    alerta_id: uuid.UUID | None = None


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

    @model_validator(mode="before")
    @classmethod
    def _ubicacion_anidada(cls, valores: Any) -> Any:
        """Lift `ubicacion.{barrio,latitud,longitud}` to the top level.

        The schema Emergencies registered in the catalogue nests the location
        and declares the coordinates as **strings**, while the contract they
        described to us had all three loose. Reading only the loose ones would
        make `escalar_por_incidente` start from an empty neighbourhood and
        escalate nothing, with no error anywhere: the handler would run, find
        no claims and log a success.
        """
        if not isinstance(valores, dict):
            return valores
        ubicacion = valores.get("ubicacion")
        if not isinstance(ubicacion, dict):
            return valores
        completado = dict(valores)
        for campo in ("barrio", "latitud", "longitud"):
            if completado.get(campo) is None and ubicacion.get(campo) is not None:
                completado[campo] = ubicacion[campo]
        return completado


class IncidenteActualizado(BaseModel):
    """`com.citypass.emergencias.EmergenciaActualizada` (ADR 0017).

    Emergencies moving an incident along, and -- when the new state is a final
    one -- closing it. It is what tells us an incident stopped cutting the
    street, so claims filed after that are no longer caused by it.
    """

    model_config = ConfigDict(extra="allow")

    incidente_id: str = Field(
        validation_alias=AliasChoices("incidente_id", "incidenteId", "emergenciaId", "id")
    )
    estado_nuevo: str | None = Field(
        default=None, validation_alias=AliasChoices("estado_nuevo", "estadoNuevo", "estado")
    )
    estado_anterior: str | None = Field(
        default=None, validation_alias=AliasChoices("estado_anterior", "estadoAnterior")
    )
    # ISO 8601 in their schema, unlike the epoch millis of the other events.
    resuelto_at: datetime | None = Field(
        default=None, validation_alias=AliasChoices("resuelto_at", "resueltoAt")
    )


class CriticidadClimaticaAplicada(BaseModel):
    """`com.citypass.reclamos.CriticidadClimaticaAplicada` (ADR 0014).

    What this module did with an alert, in counts only. Public Spaces uses it to
    confirm the alert landed; Analytics uses it to size the event.

    No personal data on purpose: how many claims were marked says everything
    these two need, and who filed them says nothing extra to them.
    """

    alerta_id: uuid.UUID
    nivel_criticidad: NivelCriticidad
    # APLICADA when the whole run finished, FALLIDA when it broke partway.
    estado: str = "APLICADA"
    acciones_aplicadas: list[str] = Field(default_factory=list)
    reclamos_marcados: int = 0
    # Open claims that could not be placed in any area: no neighbourhood code
    # and no coordinates. It is the measure of what the free-text field costs.
    reclamos_sin_ubicacion: int = 0
    avisos_enviados: int = 0
    detalle_error: str | None = None


class CriticidadClimaticaLevantada(BaseModel):
    """`com.citypass.reclamos.CriticidadClimaticaLevantada` (ADR 0014)."""

    alerta_id: uuid.UUID
    levantada_en: datetime
    reclamos_abiertos_al_confirmar: int = 0
    # The number Analytics consumes: how many claims the alert generated.
    reclamos_creados_durante: int = 0
    subidos_de_prioridad: int = 0
    duplicados_detectados: int = 0
    abiertos_al_finalizar: int = 0
    sin_ubicacion: int = 0


class UbicacionClimatica(BaseModel):
    model_config = ConfigDict(extra="allow")

    latitud: float
    longitud: float


class CriticidadClimaticaConfirmada(BaseModel):
    """`com.citypass.espacios.CriticidadClimaticaConfirmada` (squad 3, ADR 0014).

    Public Spaces declaring bad weather over part of the city. Fields taken from
    the schema they have registered in the bus catalogue, read on 2026-11-03,
    not from the design document: `barrios` is in the schema even though the
    document said it was not, and it is what makes the primary cross possible.

    `barrios` carries a default of `[]` in their schema, so it can arrive empty:
    that is the case the geographic fallback exists for.
    """

    model_config = ConfigDict(extra="allow")

    alerta_id: uuid.UUID = Field(validation_alias=AliasChoices("alerta_id", "alertaId"))
    nivel_criticidad: NivelCriticidad = Field(
        validation_alias=AliasChoices("nivel_criticidad", "nivelCriticidad")
    )
    fenomeno: str
    barrios: list[str] = Field(default_factory=list)
    ubicaciones: list[UbicacionClimatica] = Field(default_factory=list)
    # Epoch millis in their schema (`logicalType: timestamp-millis`).
    vigencia_desde: int = Field(validation_alias=AliasChoices("vigencia_desde", "vigenciaDesde"))
    vigencia_hasta: int = Field(validation_alias=AliasChoices("vigencia_hasta", "vigenciaHasta"))
    actor_sub: str | None = Field(
        default=None, validation_alias=AliasChoices("actor_sub", "actorSub")
    )
    temperatura_min_c: float | None = Field(
        default=None, validation_alias=AliasChoices("temperatura_min_c", "temperaturaMinC")
    )
    temperatura_max_c: float | None = Field(
        default=None, validation_alias=AliasChoices("temperatura_max_c", "temperaturaMaxC")
    )


class CriticidadClimaticaFinalizada(BaseModel):
    """`com.citypass.espacios.CriticidadClimaticaFinalizada` (squad 3, ADR 0014)."""

    model_config = ConfigDict(extra="allow")

    alerta_id: uuid.UUID = Field(validation_alias=AliasChoices("alerta_id", "alertaId"))
    finalizada_en: int | None = Field(
        default=None, validation_alias=AliasChoices("finalizada_en", "finalizadaEn")
    )
    actor_sub: str | None = Field(
        default=None, validation_alias=AliasChoices("actor_sub", "actorSub")
    )


# Wordings seen or plausible from Public Spaces for `IntervencionFinalizada`.
# Deliberately short: a synonym that is not obvious belongs in a conversation
# with them, not in a guess here.
_RESULTADOS_EQUIVALENTES: dict[str, str] = {
    "COMPLETADO": ResultadoIntervencion.RESUELTO,
    "COMPLETADA": ResultadoIntervencion.RESUELTO,
    "FINALIZADO": ResultadoIntervencion.RESUELTO,
    "FINALIZADA": ResultadoIntervencion.RESUELTO,
    "RESUELTA": ResultadoIntervencion.RESUELTO,
    "EXITOSO": ResultadoIntervencion.RESUELTO,
    "RECHAZADA": ResultadoIntervencion.RECHAZADO,
    "NO_CORRESPONDE": ResultadoIntervencion.RECHAZADO,
    "DESESTIMADO": ResultadoIntervencion.RECHAZADO,
    "DESESTIMADA": ResultadoIntervencion.RECHAZADO,
}


class IntervencionFinalizada(BaseModel):
    """`com.citypass.espacios.IntervencionFinalizada` (CU-INT-01).

    Public Spaces closing the job in the street. `resultado` is what tells a
    real fix apart from a claim they did not take: both end the claim, but the
    neighbour reads something different.
    """

    model_config = ConfigDict(extra="allow")

    reclamo_id: uuid.UUID = Field(validation_alias=AliasChoices("reclamo_id", "reclamoId"))
    resultado: ResultadoIntervencion

    @field_validator("resultado", mode="before")
    @classmethod
    def _normalizar_resultado(cls, valor: Any) -> Any:
        """Map the wordings Public Spaces may send onto our two outcomes.

        Their registered schema types `resultado` as a bare `string` with no
        documented values, so a wording we do not know would fail validation and
        send the message to the DLQ -- and the claim would simply never close,
        with nothing visible on their side. These are the synonyms worth
        accepting; anything else still fails, on purpose, because guessing
        between "fixed" and "not our job" is what tells the neighbour a lie.
        """
        if not isinstance(valor, str):
            return valor
        limpio = valor.strip().upper()
        return _RESULTADOS_EQUIVALENTES.get(limpio, limpio)

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


class UbicacionActividad(BaseModel):
    model_config = ConfigDict(extra="allow")

    lat: float = Field(ge=-90, le=90, validation_alias=AliasChoices("lat", "latitud", "latitude"))
    lng: float = Field(
        ge=-180, le=180, validation_alias=AliasChoices("lng", "lon", "longitud", "longitude")
    )


class ActividadCreada(BaseModel):
    """`com.citypass.espacios.ActividadCreada` (squad 3, ADR 0013).

    Public Spaces announcing an activity. Field names follow the squad's plan
    (`actividadId`, `fechaHoraFinalizacion` in epoch millis, `ubicacion`), and
    the English ones of the first draft (`communityEventId`, `endDate`,
    `latitude`) are still accepted, so either version of their publisher works.
    """

    model_config = ConfigDict(extra="allow")

    actividad_id: str = Field(
        validation_alias=AliasChoices("actividad_id", "actividadId", "communityEventId")
    )
    titulo: str = Field(validation_alias=AliasChoices("titulo", "title"))
    # Always PROGRAMADA on creation; checked anyway in case a cancelled one is
    # ever republished with this type.
    estado: str | None = Field(default=None, validation_alias=AliasChoices("estado", "status"))
    capacidad: int | None = Field(
        default=None, validation_alias=AliasChoices("capacidad", "capacity")
    )
    # Epoch millis or ISO 8601: Pydantic reads both.
    inicio: datetime | None = Field(
        default=None, validation_alias=AliasChoices("fechaHoraInicio", "inicio", "startDate")
    )
    fin: datetime = Field(
        validation_alias=AliasChoices(
            "fechaHoraFinalizacion", "fin", "endDate", "datetimeFinalizacion"
        )
    )
    ubicacion: UbicacionActividad | None = None
    direccion: str | None = None
    espacio_nombre: str | None = Field(
        default=None, validation_alias=AliasChoices("espacio_nombre", "espacioNombre")
    )

    @model_validator(mode="before")
    @classmethod
    def _coordenadas_sueltas(cls, valores: Any) -> Any:
        """The first draft sent `latitude`/`longitude` loose instead of `ubicacion`."""
        if isinstance(valores, dict) and not valores.get("ubicacion"):
            lat = valores.get("latitude", valores.get("latitud"))
            lng = valores.get("longitude", valores.get("longitud"))
            if lat is not None and lng is not None:
                return {**valores, "ubicacion": {"lat": lat, "lng": lng}}
        return valores


class MensajeFallido(BaseModel):
    """DLQ payload: keeps the raw message and the reason it failed."""

    topic_original: str
    error: str
    payload: dict[str, Any]


def parse_envelope(raw: dict[str, Any], data_model: type[TPayload]) -> EventEnvelope[TPayload]:
    """Validate an incoming message against the envelope + expected payload."""
    return EventEnvelope[data_model].model_validate(raw)  # type: ignore[valid-type]
