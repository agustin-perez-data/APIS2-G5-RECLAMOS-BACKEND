"""Data access for notifications. Like the claims repository, it never commits."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Notificacion
from app.domain.enums import TipoNotificacion


class NotificacionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def agregar(self, notificacion: Notificacion) -> Notificacion:
        self.session.add(notificacion)
        await self.session.flush()
        return notificacion

    async def existe(
        self, destinatario_id: str, tipo: TipoNotificacion, referencia_id: uuid.UUID
    ) -> bool:
        resultado = await self.session.execute(
            select(func.count())
            .select_from(Notificacion)
            .where(
                Notificacion.destinatario_id == destinatario_id,
                Notificacion.tipo == tipo,
                Notificacion.referencia_id == referencia_id,
            )
        )
        return bool(resultado.scalar_one())

    async def obtener(self, notificacion_id: uuid.UUID) -> Notificacion | None:
        return await self.session.get(Notificacion, notificacion_id)

    async def listar(
        self, destinatario_id: str, *, solo_no_leidas: bool, page: int, size: int
    ) -> tuple[list[Notificacion], int]:
        condiciones = [Notificacion.destinatario_id == destinatario_id]
        if solo_no_leidas:
            condiciones.append(Notificacion.leida_at.is_(None))

        stmt = (
            select(Notificacion)
            .where(*condiciones)
            # id breaks ties so pages never overlap.
            .order_by(Notificacion.created_at.desc(), Notificacion.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        total_stmt = select(func.count()).select_from(Notificacion).where(*condiciones)

        items = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(total_stmt)).scalar_one()
        return list(items), int(total)

    async def contar_no_leidas(self, destinatario_id: str) -> int:
        resultado = await self.session.execute(
            select(func.count())
            .select_from(Notificacion)
            .where(
                Notificacion.destinatario_id == destinatario_id,
                Notificacion.leida_at.is_(None),
            )
        )
        return int(resultado.scalar_one())

    async def marcar_todas_leidas(self, destinatario_id: str, ahora: datetime) -> int:
        resultado = await self.session.execute(
            update(Notificacion)
            .where(
                Notificacion.destinatario_id == destinatario_id,
                Notificacion.leida_at.is_(None),
            )
            .values(leida_at=ahora)
        )
        return int(resultado.rowcount or 0)
