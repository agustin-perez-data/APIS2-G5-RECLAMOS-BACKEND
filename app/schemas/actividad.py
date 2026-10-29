"""HTTP contracts of the mass activities (squad 3, ADR 0013)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ActividadVinculada(BaseModel):
    """What a claim shows of the mass activity it is related to."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    titulo: str
    inicio: datetime
    fin: datetime


class ActividadOut(ActividadVinculada):
    capacidad: int
    latitud: float
    longitud: float
    direccion: str | None
    espacio_nombre: str | None
    reclamos_relacionados: int = Field(
        default=0, description="Reclamos cargados en la zona mientras duraba la actividad"
    )
