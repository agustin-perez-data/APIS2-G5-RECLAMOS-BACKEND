"""A mass activity announced by Public Spaces (squad 3, ADR 0013).

Kept so that the claims filed around it can be related to it: when a festival
ends, the overflowing bins and the noise reports in the square belong to the
same story, and the operator sees them together.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ActividadMasiva(Base, TimestampMixin):
    __tablename__ = "actividades_masivas"
    __table_args__ = (
        # The lookup run on every filing: activities already started whose
        # window has not closed yet.
        Index("ix_actividades_masivas_inicio_fin", "inicio", "fin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Public Spaces' own id. The UNIQUE makes consumption idempotent: a
    # redelivered event cannot register the same activity twice.
    actividad_origen_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    capacidad: Mapped[int] = mapped_column(Integer, nullable=False)

    # Centre of the area. Required: an activity without coordinates cannot
    # relate anything, so it is never stored.
    latitud: Mapped[float] = mapped_column(Float, nullable=False)
    longitud: Mapped[float] = mapped_column(Float, nullable=False)
    direccion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    espacio_nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)

    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fin: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ActividadMasiva {self.id} {self.titulo!r}>"
