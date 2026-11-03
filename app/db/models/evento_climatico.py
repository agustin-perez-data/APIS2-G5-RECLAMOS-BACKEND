"""A weather alert declared by Public Spaces (squad 3, ADR 0014).

Kept because the alert spans time: it arrives confirmed, becomes active at
`vigencia_desde`, and ends when they say so. The claims filed while it is active
get marked with its id, and when it ends we have to find them again -- so the
alert cannot live only inside the event that announced it.

The area is ours to work out. Their event carries the points they consulted, not
a polygon, so `ubicaciones` is stored as-is and the radius comes from the
configured policy for the level.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin
from app.db.types import enum_column
from app.domain.enums import EstadoEventoClimatico, NivelCriticidad


class EventoClimatico(Base, TimestampMixin):
    __tablename__ = "eventos_climaticos"
    __table_args__ = (
        # The lookup run when a claim is filed: alerts that have not finished.
        Index("ix_eventos_climaticos_estado_vigencia", "estado", "vigencia_desde"),
    )

    # Public Spaces' own id, and the one that travels in our events. It is the
    # primary key on purpose: the same alert must never be stored twice, however
    # many times the bus redelivers its event.
    alerta_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)

    nivel: Mapped[NivelCriticidad] = mapped_column(
        enum_column(NivelCriticidad, "nivel_criticidad"), nullable=False
    )
    # Their enum has nine symbols; stored as text because it is their vocabulary,
    # not ours, and we only pass it through to the citizen-facing message.
    fenomeno: Mapped[str] = mapped_column(String(40), nullable=False)

    # The points they consulted, as `[{"latitud": ..., "longitud": ...}]`. Not
    # normalised into rows: nothing queries them individually, they are read
    # whole to work out the affected area.
    ubicaciones: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    vigencia_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    vigencia_hasta: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    estado: Mapped[EstadoEventoClimatico] = mapped_column(
        enum_column(EstadoEventoClimatico, "estado_evento_climatico"),
        nullable=False,
        default=EstadoEventoClimatico.CONFIRMADA,
    )

    # Their event carries no version field, so ordering comes from the envelope's
    # `occurredAt`: an update older than this one is discarded. Without it, a
    # redelivered CONFIRMADA could undo a FINALIZADA that already arrived.
    ultimo_occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<EventoClimatico {self.alerta_id} {self.nivel} {self.estado}>"
