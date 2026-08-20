"""Neighbour endorsements ("this happens to me too").

They drive prioritisation: several neighbours endorsing the same claim escalate
it automatically (see `ReclamoService.adherir`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow

if TYPE_CHECKING:
    from app.db.models.reclamo import Reclamo


class Adhesion(Base):
    __tablename__ = "reclamo_adhesiones"
    __table_args__ = (
        # One endorsement per citizen. The UNIQUE is the real guarantee; the
        # check in the service layer only exists to return a nice error.
        UniqueConstraint("reclamo_id", "ciudadano_id", name="uq_adhesion_reclamo_ciudadano"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    reclamo_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("reclamos.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ciudadano_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    reclamo: Mapped[Reclamo] = relationship(back_populates="adhesiones")
