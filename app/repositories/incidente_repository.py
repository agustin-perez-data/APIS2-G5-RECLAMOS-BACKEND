"""Data access for the road incidents reported by Emergencies (ADR 0017).

Like every repository here it flushes but never commits: the unit of work
belongs to the service.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import IncidenteVial


class IncidenteRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def agregar(self, incidente: IncidenteVial) -> IncidenteVial:
        self.session.add(incidente)
        await self.session.flush()
        return incidente

    async def obtener_por_origen(self, incidente_origen_id: str) -> IncidenteVial | None:
        """Idempotency key: Emergencies' id for the incident."""
        resultado = await self.session.execute(
            select(IncidenteVial).where(IncidenteVial.incidente_origen_id == incidente_origen_id)
        )
        return resultado.scalar_one_or_none()

    async def abiertos(
        self,
        *,
        momento: datetime,
        inicio_desde: datetime,
        caja: tuple[float, float, float, float],
    ) -> list[IncidenteVial]:
        """Incidents already started and not closed, inside the box.

        **Closed means `fin` set, with no comparison against the clock.** The
        first version asked for `fin >= momento` as well, which left a
        just-closed incident open for the width of the timestamp: close it and
        file a claim in the same instant and the claim still came out caused by
        it. In production that window is sub-millisecond and harmless, but the
        rule it encodes is wrong -- Emergencies closes an incident when the
        street is already clear, never in the future -- and it made the test
        for exactly this non-deterministic.

        `inicio_desde` is the safety net: an incident whose closing event never
        arrived stops being open on its own. Only the cheap filters run here;
        the exact distance is measured in the service over this short list.
        """
        lat_min, lat_max, lon_min, lon_max = caja
        stmt = select(IncidenteVial).where(
            IncidenteVial.inicio <= momento,
            IncidenteVial.inicio >= inicio_desde,
            IncidenteVial.fin.is_(None),
            IncidenteVial.latitud.between(lat_min, lat_max),
            IncidenteVial.longitud.between(lon_min, lon_max),
        )
        return list((await self.session.execute(stmt)).scalars().all())
