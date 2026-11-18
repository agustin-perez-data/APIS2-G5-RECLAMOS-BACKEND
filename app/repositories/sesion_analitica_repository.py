"""Shared session storage; mutations never commit the caller's transaction."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.sesion_analitica import SesionAnalitica


class SesionAnaliticaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def agregar(self, sesion: SesionAnalitica) -> None:
        self.session.add(sesion)
        await self.session.flush()

    async def obtener(self, identificador_hash: str) -> SesionAnalitica | None:
        resultado = await self.session.execute(
            select(SesionAnalitica)
            .where(SesionAnalitica.identificador_hash == identificador_hash)
            .execution_options(populate_existing=True)
        )
        return resultado.scalar_one_or_none()

    async def consumir(self, identificador_hash: str, ahora: datetime) -> SesionAnalitica | None:
        # DELETE takes a row lock in PostgreSQL: only one process can rotate it.
        resultado = await self.session.execute(
            delete(SesionAnalitica)
            .where(
                SesionAnalitica.identificador_hash == identificador_hash,
                SesionAnalitica.vence_at > ahora,
            )
            .returning(SesionAnalitica)
        )
        return resultado.scalar_one_or_none()

    async def eliminar(self, identificador_hash: str) -> bool:
        resultado = await self.session.execute(
            delete(SesionAnalitica)
            .where(SesionAnalitica.identificador_hash == identificador_hash)
            .returning(SesionAnalitica.identificador_hash)
        )
        return resultado.scalar_one_or_none() is not None

    async def eliminar_expiradas(self, ahora: datetime) -> int:
        resultado = await self.session.execute(
            delete(SesionAnalitica)
            .where(SesionAnalitica.vence_at <= ahora)
            .returning(SesionAnalitica.identificador_hash)
        )
        return len(resultado.scalars().all())
