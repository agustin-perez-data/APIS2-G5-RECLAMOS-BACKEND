"""Data access for weather alerts and for the events already processed.

Like every repository here it flushes but never commits: the unit of work
belongs to the service. That matters more than usual for `marcar_procesado`,
because the whole point is that the event id and the work it caused land in the
same transaction or neither does.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventoClimatico, EventoProcesado
from app.domain.enums import EstadoEventoClimatico


class EventoClimaticoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Alerts -------------------------------------------------------------

    async def obtener(self, alerta_id: uuid.UUID) -> EventoClimatico | None:
        return await self.session.get(EventoClimatico, alerta_id)

    async def agregar(self, evento: EventoClimatico) -> EventoClimatico:
        self.session.add(evento)
        await self.session.flush()
        return evento

    async def activas(self) -> list[EventoClimatico]:
        """Alerts that have not finished, newest first.

        Read when a claim is filed, which is why `estado` is indexed: there is
        no scheduler flipping CONFIRMADA to ACTIVA, the window is checked here.
        """
        resultado = await self.session.execute(
            select(EventoClimatico)
            .where(EventoClimatico.estado != EstadoEventoClimatico.FINALIZADA)
            .order_by(EventoClimatico.vigencia_desde.desc())
        )
        return list(resultado.scalars().all())

    # --- Dedup --------------------------------------------------------------

    async def ya_procesado(self, event_id: str) -> bool:
        return await self.session.get(EventoProcesado, event_id) is not None

    async def marcar_procesado(self, event_id: str, tipo: str) -> None:
        """Record the event id **in the caller's transaction**.

        Written before the work, not after: if the handler fails, the rollback
        takes this row with it and the redelivery is processed as it should be.
        Writing it afterwards, or committing it on its own, would turn a failed
        handling into an event that can never be retried.
        """
        self.session.add(EventoProcesado(event_id=event_id, tipo=tipo))
        await self.session.flush()
