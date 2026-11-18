"""Short-lived Analytics sessions. Only a verifier and encrypted JWT are stored."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SesionAnalitica(Base):
    __tablename__ = "sesiones_analitica"

    identificador_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    usuario_id: Mapped[str] = mapped_column(String(255), nullable=False)
    token_cifrado: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    vence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
