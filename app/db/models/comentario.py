"""Neighbour comments and official replies from the city."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow

if TYPE_CHECKING:
    from app.db.models.reclamo import Reclamo


class Comentario(Base):
    __tablename__ = "reclamo_comentarios"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reclamo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reclamos.id", ondelete="CASCADE"), nullable=False, index=True
    )

    autor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    autor_nombre: Mapped[str | None] = mapped_column(String(150), nullable=True)
    texto: Mapped[str] = mapped_column(Text, nullable=False)

    # True when an operator or admin wrote it: the app highlights those.
    es_oficial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    reclamo: Mapped[Reclamo] = relationship(back_populates="comentarios")
