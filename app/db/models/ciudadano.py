"""A neighbour registered in this module.

Group 2's Federated Login authenticates municipal staff only, so the people who
file claims have their account here instead (see ADR 0011).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, UniqueConstraint, Uuid
from sqlalchemy import DateTime as SADateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Ciudadano(Base, TimestampMixin):
    __tablename__ = "ciudadanos"
    __table_args__ = (UniqueConstraint("email", name="uq_ciudadanos_email"),)

    # Travels as the token's `sub` and lands in `reclamos.ciudadano_id`. A UUID
    # on purpose: impossible to confuse with the IdP's `U000042`, and it does
    # not leak how many people registered.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Doubles as the username. Stored lowercase: the service normalises it on
    # the way in, which is cheaper than a functional index that SQLite (used by
    # the test suite) would not support anyway.
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)

    # Soft delete: claims keep pointing at an id that still resolves.
    activo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    ultimo_acceso_at: Mapped[datetime | None] = mapped_column(
        SADateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Ciudadano {self.id} {self.email}>"
