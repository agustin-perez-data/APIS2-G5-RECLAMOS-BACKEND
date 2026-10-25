"""Data access for citizen accounts. Like the others, it never commits."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Ciudadano


class CiudadanoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def agregar(self, ciudadano: Ciudadano) -> Ciudadano:
        self.session.add(ciudadano)
        await self.session.flush()
        return ciudadano

    async def por_email(self, email: str) -> Ciudadano | None:
        """Look one up by its already normalised email."""
        resultado = await self.session.execute(select(Ciudadano).where(Ciudadano.email == email))
        return resultado.scalar_one_or_none()
