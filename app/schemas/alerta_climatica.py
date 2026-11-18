"""What the API says about a weather alert (ADR 0014)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import EstadoEventoClimatico, NivelCriticidad


class AlertaClimaticaOut(BaseModel):
    """A weather alert in force, for the operator's panel."""

    model_config = ConfigDict(from_attributes=True)

    alerta_id: uuid.UUID
    nivel: NivelCriticidad
    fenomeno: str = Field(description="El fenomeno, con el vocabulario de Espacios Publicos")
    barrios: list[str] = Field(
        description="Barrios afectados, normalizados. Vacio si la alerta llego solo con puntos"
    )
    vigencia_desde: datetime
    vigencia_hasta: datetime
    estado: EstadoEventoClimatico

    @field_validator("vigencia_desde", "vigencia_hasta", mode="after")
    @classmethod
    def _en_utc(cls, momento: datetime) -> datetime:
        # Stored values are always UTC, but SQLite hands them back naive. Without
        # the offset a client would read the hour as local time.
        return momento if momento.tzinfo is not None else momento.replace(tzinfo=UTC)
