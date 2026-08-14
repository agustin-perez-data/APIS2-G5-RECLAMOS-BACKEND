"""The module's main aggregate: a neighbourhood claim."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime as SADateTime
from sqlalchemy import Float, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base, TimestampMixin
from app.db.types import enum_column
from app.domain.enums import (
    CanalOrigen,
    CategoriaReclamo,
    EstadoReclamo,
    OrigenClasificacion,
    PrioridadReclamo,
)

if TYPE_CHECKING:
    from app.db.models.adhesion import Adhesion
    from app.db.models.comentario import Comentario
    from app.db.models.historial import HistorialEstado


class Reclamo(Base, TimestampMixin):
    __tablename__ = "reclamos"
    __table_args__ = (
        # The two queries the back office actually runs: the inbox sorted by
        # state and priority, and the map filtered by category.
        Index("ix_reclamos_estado_prioridad", "estado", "prioridad"),
        Index("ix_reclamos_categoria_estado", "categoria", "estado"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # --- Who filed it and how ------------------------------------------------
    # `sub` claim of the JWT issued by the identity module (Group 2).
    ciudadano_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    canal: Mapped[CanalOrigen] = mapped_column(
        enum_column(CanalOrigen, "canal_origen"), default=CanalOrigen.APP, nullable=False
    )

    # --- Content -------------------------------------------------------------
    titulo: Mapped[str] = mapped_column(String(150), nullable=False)
    descripcion: Mapped[str] = mapped_column(Text, nullable=False)
    fotos: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # --- Classification ------------------------------------------------------
    categoria: Mapped[CategoriaReclamo] = mapped_column(
        enum_column(CategoriaReclamo, "categoria_reclamo"), nullable=False, index=True
    )
    prioridad: Mapped[PrioridadReclamo] = mapped_column(
        enum_column(PrioridadReclamo, "prioridad_reclamo"),
        default=PrioridadReclamo.MEDIA,
        nullable=False,
    )
    origen_clasificacion: Mapped[OrigenClasificacion] = mapped_column(
        enum_column(OrigenClasificacion, "origen_clasificacion"),
        default=OrigenClasificacion.CIUDADANO,
        nullable=False,
    )
    # Classifier confidence in [0, 1] when the model picked the category.
    confianza_clasificacion: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Location ------------------------------------------------------------
    direccion: Mapped[str | None] = mapped_column(String(255), nullable=True)
    barrio: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    latitud: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitud: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Case handling -------------------------------------------------------
    estado: Mapped[EstadoReclamo] = mapped_column(
        enum_column(EstadoReclamo, "estado_reclamo"),
        default=EstadoReclamo.RECIBIDO,
        nullable=False,
        index=True,
    )
    asignado_a: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    area_responsable: Mapped[str | None] = mapped_column(String(120), nullable=True)
    resolucion: Mapped[str | None] = mapped_column(Text, nullable=True)
    resuelto_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)
    cerrado_at: Mapped[datetime | None] = mapped_column(SADateTime(timezone=True), nullable=True)

    # --- Citizen participation -----------------------------------------------
    # Denormalised counter: the inbox sorts by endorsements and we don't want a
    # COUNT per row. `ReclamoService.adherir` keeps it in sync.
    adhesiones_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # --- Event-driven traceability -------------------------------------------
    # Propagated into every event we publish so a single interaction can be
    # followed across modules.
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # If the claim was born from another module's event, we store its event_id.
    # The UNIQUE makes consumption idempotent: a redelivery cannot duplicate it.
    evento_origen_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

    historial: Mapped[list[HistorialEstado]] = relationship(
        back_populates="reclamo",
        cascade="all, delete-orphan",
        order_by="HistorialEstado.created_at",
        lazy="selectin",
    )
    comentarios: Mapped[list[Comentario]] = relationship(
        back_populates="reclamo",
        cascade="all, delete-orphan",
        order_by="Comentario.created_at",
        lazy="selectin",
    )
    adhesiones: Mapped[list[Adhesion]] = relationship(
        back_populates="reclamo",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Reclamo {self.id} {self.categoria} {self.estado}>"
