"""Data access for the Reclamo aggregate.

The repository builds queries and flushes, but it never **commits**: the unit of
work belongs to the service, which is the only layer that knows when a business
operation is actually complete.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Adhesion, Comentario, HistorialEstado, Reclamo
from app.domain.enums import CategoriaReclamo, EstadoReclamo, PrioridadReclamo

ORDENES_PERMITIDOS: dict[str, tuple[str, bool]] = {
    # public alias -> (column, descending)
    "recientes": ("created_at", True),
    "antiguos": ("created_at", False),
    "adhesiones": ("adhesiones_count", True),
    "actualizados": ("updated_at", True),
}


@dataclass(slots=True)
class FiltroReclamos:
    estado: EstadoReclamo | None = None
    categoria: CategoriaReclamo | None = None
    prioridad: PrioridadReclamo | None = None
    ciudadano_id: str | None = None
    asignado_a: str | None = None
    barrio: str | None = None
    texto: str | None = None
    desde: datetime | None = None
    hasta: datetime | None = None
    orden: str = "recientes"
    estados: list[EstadoReclamo] = field(default_factory=list)


class ReclamoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # --- Writes --------------------------------------------------------------
    async def agregar(self, reclamo: Reclamo) -> Reclamo:
        self.session.add(reclamo)
        await self.session.flush()
        return reclamo

    async def agregar_historial(self, historial: HistorialEstado) -> HistorialEstado:
        self.session.add(historial)
        await self.session.flush()
        return historial

    async def agregar_comentario(self, comentario: Comentario) -> Comentario:
        self.session.add(comentario)
        await self.session.flush()
        return comentario

    async def agregar_adhesion(self, adhesion: Adhesion) -> Adhesion:
        self.session.add(adhesion)
        await self.session.flush()
        return adhesion

    # --- Reads ---------------------------------------------------------------
    async def obtener(self, reclamo_id: uuid.UUID) -> Reclamo | None:
        return await self.session.get(Reclamo, reclamo_id)

    async def obtener_por_evento_origen(self, evento_id: str) -> Reclamo | None:
        """Idempotency key used when consuming other modules' events."""
        resultado = await self.session.execute(
            select(Reclamo).where(Reclamo.evento_origen_id == evento_id)
        )
        return resultado.scalar_one_or_none()

    async def existe_adhesion(self, reclamo_id: uuid.UUID, ciudadano_id: str) -> bool:
        resultado = await self.session.execute(
            select(func.count())
            .select_from(Adhesion)
            .where(Adhesion.reclamo_id == reclamo_id, Adhesion.ciudadano_id == ciudadano_id)
        )
        return bool(resultado.scalar_one())

    async def comentarios_de(self, reclamo_id: uuid.UUID) -> list[Comentario]:
        resultado = await self.session.execute(
            select(Comentario)
            .where(Comentario.reclamo_id == reclamo_id)
            .order_by(Comentario.created_at)
        )
        return list(resultado.scalars().all())

    async def historial_de(self, reclamo_id: uuid.UUID) -> list[HistorialEstado]:
        resultado = await self.session.execute(
            select(HistorialEstado)
            .where(HistorialEstado.reclamo_id == reclamo_id)
            .order_by(HistorialEstado.created_at)
        )
        return list(resultado.scalars().all())

    def _aplicar_filtros(self, stmt: Select, filtro: FiltroReclamos) -> Select:
        if filtro.estado is not None:
            stmt = stmt.where(Reclamo.estado == filtro.estado)
        if filtro.estados:
            stmt = stmt.where(Reclamo.estado.in_(filtro.estados))
        if filtro.categoria is not None:
            stmt = stmt.where(Reclamo.categoria == filtro.categoria)
        if filtro.prioridad is not None:
            stmt = stmt.where(Reclamo.prioridad == filtro.prioridad)
        if filtro.ciudadano_id:
            stmt = stmt.where(Reclamo.ciudadano_id == filtro.ciudadano_id)
        if filtro.asignado_a:
            stmt = stmt.where(Reclamo.asignado_a == filtro.asignado_a)
        if filtro.barrio:
            stmt = stmt.where(Reclamo.barrio == filtro.barrio)
        if filtro.texto:
            patron = f"%{filtro.texto.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Reclamo.titulo).like(patron),
                    func.lower(Reclamo.descripcion).like(patron),
                )
            )
        if filtro.desde:
            stmt = stmt.where(Reclamo.created_at >= filtro.desde)
        if filtro.hasta:
            stmt = stmt.where(Reclamo.created_at <= filtro.hasta)
        return stmt

    async def listar(
        self, filtro: FiltroReclamos, *, page: int = 1, size: int = 20
    ) -> tuple[list[Reclamo], int]:
        columna, desc = ORDENES_PERMITIDOS.get(filtro.orden, ORDENES_PERMITIDOS["recientes"])
        criterio = getattr(Reclamo, columna)

        stmt = self._aplicar_filtros(select(Reclamo), filtro)
        stmt = stmt.order_by(criterio.desc() if desc else criterio.asc())
        stmt = stmt.offset((page - 1) * size).limit(size)

        total_stmt = self._aplicar_filtros(select(func.count()).select_from(Reclamo), filtro)

        items = (await self.session.execute(stmt)).scalars().all()
        total = (await self.session.execute(total_stmt)).scalar_one()
        return list(items), int(total)

    # --- Metrics -------------------------------------------------------------
    async def _conteo_por(self, columna) -> list[tuple[str, int]]:
        resultado = await self.session.execute(
            select(columna, func.count()).group_by(columna).order_by(func.count().desc())
        )
        return [(str(clave), int(cantidad)) for clave, cantidad in resultado.all()]

    async def estadisticas(self) -> dict:
        total = (await self.session.execute(select(func.count()).select_from(Reclamo))).scalar_one()

        # The average is computed in Python: `AVG` over date differences has a
        # different syntax in Postgres and SQLite (used by the tests), and the
        # volume of resolved claims does not justify optimising it yet.
        resueltos = await self.session.execute(
            select(Reclamo.created_at, Reclamo.resuelto_at).where(Reclamo.resuelto_at.is_not(None))
        )
        horas = [(resuelto - creado).total_seconds() / 3600 for creado, resuelto in resueltos.all()]

        return {
            "total": int(total),
            "por_estado": await self._conteo_por(Reclamo.estado),
            "por_categoria": await self._conteo_por(Reclamo.categoria),
            "por_prioridad": await self._conteo_por(Reclamo.prioridad),
            "tiempo_resolucion_horas_promedio": (
                round(sum(horas) / len(horas), 2) if horas else None
            ),
        }
