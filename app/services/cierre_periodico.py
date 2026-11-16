"""Periodic auto-close of resolved claims (US-17, ADR 0025).

`ReclamoService.cerrar_resueltos_vencidos` decides what closes. This is only
the clock that calls it: a loop that runs inside whichever process is up, the
API in production and the worker locally.

The clock is in-process on purpose. The first design had GitHub Actions call a
maintenance endpoint once a day, and GitHub drops most scheduled runs of this
repository, so the claims simply stayed open and nothing reported a failure: a
workflow that never starts never fails.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.session import session_scope
from app.events.producer import EventPublisher
from app.services.reclamo_service import ReclamoService

log = get_logger(__name__)

Sesiones = Callable[[], AbstractAsyncContextManager[AsyncSession]]


async def cerrar_vencidos_una_vez(
    publisher: EventPublisher, sesiones: Sesiones = session_scope
) -> int:
    """One pass. Returns how many claims it closed; never raises."""
    try:
        async with sesiones() as session:
            cerrados = await ReclamoService(session, publisher).cerrar_resueltos_vencidos()
    except Exception:  # noqa: BLE001 - one bad pass must not end the loop
        log.exception("cierre_automatico.error")
        return 0
    if cerrados:
        log.info("cierre_automatico.cerrados", cantidad=len(cerrados))
    return len(cerrados)


async def cierre_automatico_periodico(
    publisher: EventPublisher,
    *,
    espera_inicial_segundos: float,
    intervalo_segundos: float,
    sesiones: Sesiones = session_scope,
) -> None:
    """Close what is due, then again every `intervalo_segundos`, until cancelled.

    The first pass comes shortly after start-up rather than one interval later:
    the service sleeps when nobody uses it, and a process that is rarely up for
    a whole interval would otherwise never close anything.
    """
    await asyncio.sleep(espera_inicial_segundos)
    while True:
        await cerrar_vencidos_una_vez(publisher, sesiones)
        await asyncio.sleep(intervalo_segundos)
