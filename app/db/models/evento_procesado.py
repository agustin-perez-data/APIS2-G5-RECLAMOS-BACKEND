"""Event ids already handled, so a redelivery does nothing twice.

The gateway delivers at least once -- its own README says so in the webhook
section: "pueden perderse eventos o haber duplicados". Until now that cost
nothing, because the handlers happened to be idempotent on their own. The
weather alert breaks that: handling CONFIRMADA notifies every affected
neighbour, and a redelivery would notify all of them again.

`evento_origen_id` on `reclamos` does not cover this. It marks the claim that
was born from another module's event, so it only exists when a claim was
created; an alert that marks thirty claims creates none.

The row is written in the same transaction as the handler's work: either both
land or neither does. See ADR 0014.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventoProcesado(Base):
    __tablename__ = "eventos_procesados"

    # The bus' `metadata.eventId`, unique per delivery attempt of a given event.
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Kept for diagnosis only: which type it was, so a glance at the table says
    # what has been flowing without crossing it against the logs.
    tipo: Mapped[str] = mapped_column(String(120), nullable=False)
    procesado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<EventoProcesado {self.event_id} {self.tipo}>"
