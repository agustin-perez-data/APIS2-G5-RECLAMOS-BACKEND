"""Periodic session cleanup, isolated from the business maintenance loop."""

from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.sesion_analitica_service import SesionAnaliticaService


async def limpiar_sesiones_periodicamente(cfg: Settings, intervalo: float = 60) -> None:
    while True:
        try:
            async with SessionLocal() as session:
                await SesionAnaliticaService(session, cfg).limpiar_expiradas()
        except Exception:
            # Never include exception messages: DB parameters may be sensitive.
            get_logger(__name__).warning("analitica.limpieza_fallida")
        await asyncio.sleep(intervalo)
