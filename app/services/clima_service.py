"""Weather alerts: deduplication and the alert's own lifecycle (ADR 0014).

Step 2 of the weather alert mode. This records what Public Spaces tells us and
keeps the alert's state straight; marking claims and moving priorities is step 3
and lives in `ReclamoService`.

Two problems are solved here, and both come from the same place -- the bus
delivers at least once and their event carries no version number:

**Duplicates.** The same event can arrive more than once. Handling a
confirmation notifies every affected neighbour, so a redelivery would notify all
of them again. `eventos_procesados` holds the ids already seen, written in the
same transaction as the work.

**Order.** Two deliveries of the same alert can arrive out of order. With no
version field, the only thing to sort by is when the bus received each one, so
an event older than the last one applied is discarded.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EventoClimatico
from app.domain.barrios import normalizar_barrio
from app.domain.enums import EstadoEventoClimatico
from app.events.contracts import (
    CriticidadClimaticaConfirmada,
    CriticidadClimaticaFinalizada,
)
from app.repositories.evento_climatico_repository import EventoClimaticoRepository


def _desde_epoch_millis(valor: int | None) -> datetime | None:
    """Their schema sends `timestamp-millis`; we store aware datetimes in UTC."""
    if valor is None:
        return None
    return datetime.fromtimestamp(valor / 1000, tz=UTC)


def _con_zona(momento: datetime) -> datetime:
    """Read a stored timestamp back as aware, whatever the engine returned.

    PostgreSQL gives back `timestamptz` with its offset, SQLite -- which the
    test suite runs on -- gives back a naive datetime. Comparing the two raises
    `TypeError`, so everything read from the database passes through here.
    Stored values are always UTC, so assuming UTC is correct and not a guess.
    """
    return momento if momento.tzinfo is not None else momento.replace(tzinfo=UTC)


def _normalizar_barrios(barrios: list[str]) -> list[str]:
    """Normalise the alert's side once, when it is stored.

    The claim's side is normalised on write too (`reclamos.barrio_codigo`), so
    by the time the two are compared both are already codes and the query is a
    plain `IN` against an index.
    """
    vistos: list[str] = []
    for barrio in barrios:
        codigo = normalizar_barrio(barrio)
        if codigo and codigo not in vistos:
            vistos.append(codigo)
    return vistos


class ClimaService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EventoClimaticoRepository(session)

    async def ya_procesado(self, event_id: str) -> bool:
        return await self.repo.ya_procesado(event_id)

    async def marcar_procesado(self, event_id: str, tipo: str) -> None:
        await self.repo.marcar_procesado(event_id, tipo)

    async def registrar_confirmada(
        self, datos: CriticidadClimaticaConfirmada, *, occurred_at: datetime
    ) -> EventoClimatico | None:
        """Store the alert, or update it if a newer version of it arrives.

        Returns `None` when the event is older than what we already applied, so
        the caller knows there is nothing else to do.
        """
        existente = await self.repo.obtener(datos.alerta_id)
        if existente is not None and not self._es_mas_nuevo(existente, occurred_at):
            return None

        barrios = _normalizar_barrios(datos.barrios)
        ubicaciones = [{"latitud": u.latitud, "longitud": u.longitud} for u in datos.ubicaciones]
        desde = _desde_epoch_millis(datos.vigencia_desde)
        hasta = _desde_epoch_millis(datos.vigencia_hasta)
        assert desde is not None and hasta is not None  # noqa: S101 - required in their schema

        if existente is None:
            return await self.repo.agregar(
                EventoClimatico(
                    alerta_id=datos.alerta_id,
                    nivel=datos.nivel_criticidad,
                    fenomeno=datos.fenomeno,
                    barrios=barrios,
                    ubicaciones=ubicaciones,
                    vigencia_desde=desde,
                    vigencia_hasta=hasta,
                    estado=EstadoEventoClimatico.CONFIRMADA,
                    ultimo_occurred_at=occurred_at,
                )
            )

        # An update: the level or the area can change while the alert is live.
        # `estado` is left alone so an update does not revive a finished alert.
        existente.nivel = datos.nivel_criticidad
        existente.fenomeno = datos.fenomeno
        existente.barrios = barrios
        existente.ubicaciones = ubicaciones
        existente.vigencia_desde = desde
        existente.vigencia_hasta = hasta
        existente.ultimo_occurred_at = occurred_at
        await self.session.flush()
        return existente

    async def registrar_finalizada(
        self, datos: CriticidadClimaticaFinalizada, *, occurred_at: datetime
    ) -> EventoClimatico | None:
        """Close the alert. `None` when it is unknown or the event is stale."""
        evento = await self.repo.obtener(datos.alerta_id)
        if evento is None or not self._es_mas_nuevo(evento, occurred_at):
            return None

        evento.estado = EstadoEventoClimatico.FINALIZADA
        evento.ultimo_occurred_at = occurred_at
        await self.session.flush()
        return evento

    @staticmethod
    def _es_mas_nuevo(evento: EventoClimatico, occurred_at: datetime) -> bool:
        """Their event has no version, so the bus' timestamp is the only order.

        A delivery with no timestamp of its own is treated as current: dropping
        it would be worse than applying it, because the alternative is ignoring
        an alert that is really happening.
        """
        if evento.ultimo_occurred_at is None:
            return True
        return occurred_at >= _con_zona(evento.ultimo_occurred_at)
