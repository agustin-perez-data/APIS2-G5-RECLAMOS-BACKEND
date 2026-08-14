"""HTTP contracts of the claims module."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.enums import (
    CanalOrigen,
    CategoriaReclamo,
    EstadoReclamo,
    OrigenClasificacion,
    PrioridadReclamo,
)


# --- Input -------------------------------------------------------------------
class ReclamoCrear(BaseModel):
    titulo: str = Field(min_length=5, max_length=150)
    descripcion: str = Field(min_length=10, max_length=5000)
    # Left out, the classifier fills them in (see `app/services/clasificador.py`).
    categoria: CategoriaReclamo | None = None
    prioridad: PrioridadReclamo | None = None
    direccion: str | None = Field(default=None, max_length=255)
    barrio: str | None = Field(default=None, max_length=120)
    latitud: float | None = Field(default=None, ge=-90, le=90)
    longitud: float | None = Field(default=None, ge=-180, le=180)
    fotos: list[str] = Field(default_factory=list, max_length=5)
    canal: CanalOrigen = CanalOrigen.APP

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "titulo": "Luminaria apagada en la plaza",
                "descripcion": "Hace una semana que no funciona el alumbrado de la cuadra.",
                "direccion": "Rivadavia 800",
                "barrio": "Centro",
                "latitud": -34.6037,
                "longitud": -58.3816,
                "fotos": [],
            }
        }
    )


class CambioEstado(BaseModel):
    estado: EstadoReclamo
    motivo: str | None = Field(default=None, max_length=1000)
    asignado_a: str | None = Field(default=None, max_length=128)
    area_responsable: str | None = Field(default=None, max_length=120)
    resolucion: str | None = Field(default=None, max_length=2000)


class ComentarioCrear(BaseModel):
    texto: str = Field(min_length=1, max_length=2000)


class ClasificacionPedido(BaseModel):
    titulo: str = Field(min_length=1, max_length=150)
    descripcion: str = Field(min_length=1, max_length=5000)


# --- Output ------------------------------------------------------------------
class HistorialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    estado_anterior: EstadoReclamo | None
    estado_nuevo: EstadoReclamo
    motivo: str | None
    usuario_id: str
    created_at: datetime


class ComentarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reclamo_id: uuid.UUID
    autor_id: str
    autor_nombre: str | None
    texto: str
    es_oficial: bool
    created_at: datetime


class ReclamoResumen(BaseModel):
    """Lightweight projection for lists and map views."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    titulo: str
    categoria: CategoriaReclamo
    prioridad: PrioridadReclamo
    estado: EstadoReclamo
    barrio: str | None
    latitud: float | None
    longitud: float | None
    adhesiones_count: int
    created_at: datetime


class ReclamoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ciudadano_id: str
    titulo: str
    descripcion: str
    categoria: CategoriaReclamo
    prioridad: PrioridadReclamo
    estado: EstadoReclamo
    origen_clasificacion: OrigenClasificacion
    confianza_clasificacion: float | None
    canal: CanalOrigen
    direccion: str | None
    barrio: str | None
    latitud: float | None
    longitud: float | None
    fotos: list[str]
    asignado_a: str | None
    area_responsable: str | None
    resolucion: str | None
    adhesiones_count: int
    correlation_id: str | None
    created_at: datetime
    updated_at: datetime
    resuelto_at: datetime | None
    cerrado_at: datetime | None


class ReclamoDetalle(ReclamoOut):
    historial: list[HistorialOut] = Field(default_factory=list)
    comentarios: list[ComentarioOut] = Field(default_factory=list)


class AdhesionOut(BaseModel):
    reclamo_id: uuid.UUID
    adhesiones_count: int
    prioridad: PrioridadReclamo


class SugerenciaClasificacion(BaseModel):
    categoria: CategoriaReclamo
    prioridad: PrioridadReclamo
    confianza: float = Field(ge=0, le=1)
    # Terms from the text that drove the suggestion. They make the result
    # explainable to the operator reviewing it.
    evidencia: list[str] = Field(default_factory=list)
    modelo: str


class ConteoPorClave(BaseModel):
    clave: str
    cantidad: int


class Estadisticas(BaseModel):
    """Summary for our own dashboard and for Group 8 (Urban Analytics)."""

    total: int
    por_estado: list[ConteoPorClave]
    por_categoria: list[ConteoPorClave]
    por_prioridad: list[ConteoPorClave]
    tiempo_resolucion_horas_promedio: float | None
