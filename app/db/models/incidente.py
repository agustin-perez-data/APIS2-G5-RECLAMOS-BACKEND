"""Road incidents reported by Emergencies, kept so claims can point at them."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String
from sqlalchemy import Uuid as SAUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class IncidenteVial(Base, TimestampMixin):
    """An Emergencies incident that cuts circulation (ADR 0017).

    We keep only the ones that cut circulation and carry a position: those are
    the ones a claim filed nearby can be caused by. A medical emergency concerns
    one person, not the street.

    The incident is Emergencies' record, not ours. We store a copy because
    Analytics asked to count claims caused by a road incident, and relating a
    claim at filing time needs the incident to be queryable right then.
    """

    __tablename__ = "incidentes_viales"
    __table_args__ = (
        # The lookup run on every filing: incidents open at a given moment.
        Index("ix_incidentes_viales_inicio_fin", "inicio", "fin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(SAUuid, primary_key=True, default=uuid.uuid4)
    # Emergencies' own id. The UNIQUE makes consumption idempotent: a redelivered
    # event cannot store the same incident twice.
    incidente_origen_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    tipo: Mapped[str | None] = mapped_column(String(80), nullable=True)
    severidad: Mapped[str | None] = mapped_column(String(40), nullable=True)

    barrio: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Required: an incident without a position cannot relate anything, so one
    # that arrives without coordinates is escalated but never stored.
    latitud: Mapped[float] = mapped_column(Float, nullable=False)
    longitud: Mapped[float] = mapped_column(Float, nullable=False)

    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set when Emergencies publishes the closing update. Null means still open
    # -- but see `incidente_vigencia_horas`: an incident nobody ever closes
    # stops relating claims anyway, so a lost event cannot keep a street
    # "blocked" forever.
    fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<IncidenteVial {self.incidente_origen_id} {self.tipo}>"
