"""Data access for the mass activities announced by Public Spaces (ADR 0013).

Like every repository here it flushes but never commits: the unit of work
belongs to the service.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActividadMasiva, Reclamo


class ActividadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def agregar(self, actividad: ActividadMasiva) -> ActividadMasiva:
        self.session.add(actividad)
        await self.session.flush()
        return actividad

    async def obtener_por_origen(self, actividad_origen_id: str) -> ActividadMasiva | None:
        """Idempotency key: Public Spaces' id for the activity."""
        resultado = await self.session.execute(
            select(ActividadMasiva).where(
                ActividadMasiva.actividad_origen_id == actividad_origen_id
            )
        )
        return resultado.scalar_one_or_none()

    async def en_curso(
        self,
        *,
        momento: datetime,
        fin_desde: datetime,
        caja: tuple[float, float, float, float],
    ) -> list[ActividadMasiva]:
        """Activities already started at `momento`, ended no earlier than `fin_desde`.

        Only the cheap filters run here; the exact distance is computed in the
        service over this short list. The window is two plain comparisons so
        it reads the same on PostgreSQL and on the SQLite the tests use.
        """
        lat_min, lat_max, lon_min, lon_max = caja
        stmt = select(ActividadMasiva).where(
            ActividadMasiva.inicio <= momento,
            ActividadMasiva.fin >= fin_desde,
            ActividadMasiva.latitud.between(lat_min, lat_max),
            ActividadMasiva.longitud.between(lon_min, lon_max),
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def listar(self, *, fin_desde: datetime | None = None) -> list[ActividadMasiva]:
        """Activities whose window is still open, or all of them without `fin_desde`."""
        stmt = select(ActividadMasiva)
        if fin_desde is not None:
            stmt = stmt.where(ActividadMasiva.fin >= fin_desde)
        stmt = stmt.order_by(ActividadMasiva.inicio)
        return list((await self.session.execute(stmt)).scalars().all())

    async def reclamos_por_actividad(self, actividad_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        """How many claims each activity has related, in one query."""
        if not actividad_ids:
            return {}
        resultado = await self.session.execute(
            select(Reclamo.actividad_id, func.count())
            .where(Reclamo.actividad_id.in_(actividad_ids))
            .group_by(Reclamo.actividad_id)
        )
        return {actividad_id: int(cantidad) for actividad_id, cantidad in resultado.all()}
