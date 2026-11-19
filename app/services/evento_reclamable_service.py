"""Servicio para validar si un evento público admite reclamos."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EventoCanceladoError,
    EventoNoFinalizado,
    PlazoDeReclamoVencido,
)
from app.db.models.evento_reclamable import EventoReclamable


class EventoReclamableService:
    PLAZO_RECLAMO = timedelta(days=7)

    def __init__(self, session: AsyncSession, config=None) -> None:
        self.session = session
        self.config = config

    async def registrar_publicado(self, datos) -> None:
        resultado = await self.session.execute(
            select(EventoReclamable).where(EventoReclamable.evento_id == datos.evento_id)
        )
        evento = resultado.scalar_one_or_none()

        if evento is None:
            evento = EventoReclamable(
                evento_id=datos.evento_id,
                fin_ms=int(datos.fin.timestamp() * 1000),
                cancelado=False,
            )
            self.session.add(evento)
        else:
            evento.fin_ms = int(datos.fin.timestamp() * 1000)

        if (datos.estado or "").upper() in {"CANCELLED", "CANCELADO"}:
            evento.cancelado = True

        await self.session.commit()

    async def marcar_cancelado(self, evento_id: str) -> None:
        resultado = await self.session.execute(
            select(EventoReclamable).where(EventoReclamable.evento_id == evento_id)
        )
        evento = resultado.scalar_one_or_none()

        if evento is None:
            evento = EventoReclamable(
                evento_id=evento_id,
                fin_ms=None,
                cancelado=True,
            )
            self.session.add(evento)
        else:
            evento.cancelado = True

        await self.session.commit()

    async def validar_reclamable(
        self,
        evento_id: str,
        ahora_ms: int | None = None,
    ) -> None:
        resultado = await self.session.execute(
            select(EventoReclamable).where(EventoReclamable.evento_id == evento_id)
        )
        evento = resultado.scalar_one_or_none()

        if evento is None:
            raise EventoNoFinalizado()

        if evento.cancelado:
            raise EventoCanceladoError()

        if evento.fin_ms is None:
            raise EventoNoFinalizado()

        ahora = ahora_ms if ahora_ms is not None else int(datetime.now(UTC).timestamp() * 1000)

        if evento.fin_ms > ahora:
            raise EventoNoFinalizado()

        plazo_limite = evento.fin_ms + int(self.PLAZO_RECLAMO.total_seconds() * 1000)

        if ahora > plazo_limite:
            raise PlazoDeReclamoVencido()
