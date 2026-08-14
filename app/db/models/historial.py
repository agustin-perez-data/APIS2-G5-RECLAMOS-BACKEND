"""State-change log: audit trail and traceability for a claim."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow
from app.db.types import enum_column
from app.domain.enums import EstadoReclamo

if TYPE_CHECKING:
    from app.db.models.reclamo import Reclamo


class HistorialEstado(Base):
    __tablename__ = "reclamo_historial"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reclamo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reclamos.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Null on the first row, which records the claim being filed.
    estado_anterior: Mapped[EstadoReclamo | None] = mapped_column(
        enum_column(EstadoReclamo, "estado_reclamo"), nullable=True
    )
    estado_nuevo: Mapped[EstadoReclamo] = mapped_column(
        enum_column(EstadoReclamo, "estado_reclamo"), nullable=False
    )
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Who made the change: the JWT `sub`, or "sistema" when an event did it.
    usuario_id: Mapped[str] = mapped_column(String(128), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    reclamo: Mapped[Reclamo] = relationship(back_populates="historial")
