"""Eventos públicos sobre los que se pueden crear reclamos."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventoReclamable(Base):
    __tablename__ = "eventos_reclamables"

    evento_id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )

    fin_ms: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    cancelado: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    recibido_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
