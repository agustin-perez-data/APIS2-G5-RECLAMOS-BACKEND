"""Reservations whose event already ended (CASO-RECLAMOS-POST-EVENTO).

Public Spaces publishes `EventoFinalizado` when an event ends. We keep the
`reservaId` and the moment it ended so a claim about that event can be accepted
-- and refused when the event has not ended, or when the window to complain has
closed. One row per reservation: a redelivery finds it already there and does
nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReservaFinalizada(Base):
    __tablename__ = "eventos_finalizados"

    reserva_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # `fin` of the event, in epoch milliseconds, as the bus sends it.
    fin_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    recibido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ReservaFinalizada {self.reserva_id} fin_ms={self.fin_ms}>"
