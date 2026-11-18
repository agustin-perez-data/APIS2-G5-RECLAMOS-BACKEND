"""Reservations that already ended, and the rule that lets a claim about one in.

Public Spaces announces `EventoFinalizado`; we keep its `reservaId` and `fin`.
A citizen who files a claim over a reservation is accepted only if that event
ended and the window to complain (`reclamo_ventana_ms`, 7 days by default) has
not closed. Anything else is a 409 the citizen can act on.
"""

from __future__ import annotations

import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.exceptions import EventoNoFinalizado, PlazoDeReclamoVencido
from app.core.logging import get_logger
from app.db.models import ReservaFinalizada
from app.events.contracts import EventoFinalizado

log = get_logger(__name__)


class ReservaService:
    def __init__(self, session: AsyncSession, cfg: Settings | None = None) -> None:
        self.session = session
        self.cfg = cfg or settings

    async def registrar(self, datos: EventoFinalizado) -> ReservaFinalizada | None:
        """Keep a finished reservation; None when it was already there.

        Returning None for one already stored is what makes a redelivery
        harmless: the gateway is at-least-once.
        """
        existente = await self.session.get(ReservaFinalizada, datos.reserva_id)
        if existente is not None:
            log.info("reserva.ya_finalizada", reserva_id=datos.reserva_id)
            return None

        reserva = ReservaFinalizada(
            reserva_id=datos.reserva_id,
            fin_ms=int(datos.fin.timestamp() * 1000),
        )
        self.session.add(reserva)
        await self.session.commit()
        log.info("reserva.finalizada", reserva_id=datos.reserva_id, fin_ms=reserva.fin_ms)
        return reserva

    async def validar_reclamable(self, reserva_id: str, *, ahora_ms: int | None = None) -> None:
        """Raise a 409 unless a claim over this reservation can be accepted now."""
        reserva = await self.session.get(ReservaFinalizada, reserva_id)
        if reserva is None:
            raise EventoNoFinalizado
        ahora = ahora_ms if ahora_ms is not None else int(time.time() * 1000)
        if ahora > reserva.fin_ms + self.cfg.reclamo_ventana_ms:
            raise PlazoDeReclamoVencido
