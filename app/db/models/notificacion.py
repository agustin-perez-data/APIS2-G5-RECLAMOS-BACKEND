"""In-app notifications for the owner of a claim (ADR 0008).

Written in the same transaction as the change that triggers them, so they
never depend on the bus being up. The backend is the source of truth for the
unread count and read state: the app only reflects what it gets from here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, utcnow
from app.db.types import enum_column
from app.domain.enums import EstadoReclamo, TipoNotificacion


class Notificacion(Base):
    __tablename__ = "notificaciones"
    __table_args__ = (
        # Idempotency key: one notification per recipient for each history row
        # or comment. `referencia_id` is never null, so the key is NULL-safe.
        UniqueConstraint(
            "destinatario_id", "tipo", "referencia_id", name="uq_notificacion_referencia"
        ),
        # The inbox, newest first. A B-tree is read backwards just as well, so
        # it needs no DESC.
        Index("ix_notificaciones_destinatario_fecha", "destinatario_id", "created_at"),
        # The bell's unread count.
        Index("ix_notificaciones_destinatario_leida", "destinatario_id", "leida_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    destinatario_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reclamo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reclamos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tipo: Mapped[TipoNotificacion] = mapped_column(
        enum_column(TipoNotificacion, "tipo_notificacion"), nullable=False
    )
    # The history row (ESTADO) or the comment (COMENTARIO) behind it. Those rows
    # keep who made the change, for auditing.
    referencia_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    mensaje: Mapped[str] = mapped_column(Text, nullable=False)
    # What the app needs to render it: the new state, or the comment id.
    datos: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    leida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    @property
    def leida(self) -> bool:
        return self.leida_at is not None

    @property
    def estado_nuevo(self) -> EstadoReclamo | None:
        valor = (self.datos or {}).get("estado_nuevo")
        return EstadoReclamo(valor) if valor else None

    @property
    def comentario_id(self) -> uuid.UUID | None:
        valor = (self.datos or {}).get("comentario_id")
        return uuid.UUID(valor) if valor else None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Notificacion {self.id} {self.tipo} -> {self.destinatario_id}>"
