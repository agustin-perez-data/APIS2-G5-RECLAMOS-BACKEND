"""Road incidents and the claims they cause (ADR 0017).

Emergencies announces an incident with `EmergenciaCreada` and closes it with
`EmergenciaActualizada`. Between those two, a claim filed close to it is caused
by it, and that is what Analytics counts as `INCIDENTE_VIAL`.

Only incidents that cut circulation and carry a position are kept: a medical
emergency concerns one person, and an incident without coordinates could not
relate anything.

`registrar` and `cerrar` run from the event handlers and own their transaction.
`abierto_cerca` runs inside `ReclamoService.crear`, before the claim's commit,
so the claim and its relation are saved together or not at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.db.models import IncidenteVial
from app.domain import geo
from app.events.contracts import IncidenteCreado
from app.repositories.incidente_repository import IncidenteRepository

log = get_logger(__name__)

# What Emergencies may send for an incident that is over, in either gender and
# in both languages. Anything else leaves the incident open, which the
# `incidente_vigencia_horas` net closes on its own.
ESTADOS_CERRADOS = frozenset(
    {
        "RESUELTA",
        "RESUELTO",
        "CERRADA",
        "CERRADO",
        "FINALIZADA",
        "FINALIZADO",
        "CANCELADA",
        "CANCELADO",
        "ANULADA",
        "ANULADO",
        "RESOLVED",
        "CLOSED",
    }
)


class IncidenteService:
    def __init__(self, session: AsyncSession, cfg: Settings | None = None) -> None:
        self.session = session
        self.repo = IncidenteRepository(session)
        self.cfg = cfg or settings

    async def registrar(
        self,
        datos: IncidenteCreado,
        *,
        recibido_at: datetime,
        correlation_id: str | None = None,
    ) -> IncidenteVial | None:
        """Keep an incident, or return None when there is nothing to keep.

        Ignored: incidents that do not cut circulation and incidents without
        coordinates. Returning None for one already stored is what makes a
        redelivery harmless: the gateway is at-least-once.
        """
        if datos.afecta_circulacion is not True:
            log.info(
                "incidente.ignorado",
                incidente_id=datos.incidente_id,
                motivo="no_afecta_circulacion",
            )
            return None
        if datos.latitud is None or datos.longitud is None:
            log.info(
                "incidente.ignorado", incidente_id=datos.incidente_id, motivo="sin_coordenadas"
            )
            return None

        existente = await self.repo.obtener_por_origen(datos.incidente_id)
        if existente is not None:
            log.info("incidente.ya_registrado", incidente_id=datos.incidente_id)
            return None

        incidente = IncidenteVial(
            incidente_origen_id=datos.incidente_id,
            tipo=(datos.tipo or None) and str(datos.tipo)[:80],
            severidad=(datos.severidad or None) and str(datos.severidad)[:40],
            barrio=(datos.barrio or None) and str(datos.barrio)[:120],
            latitud=datos.latitud,
            longitud=datos.longitud,
            inicio=recibido_at,
            correlation_id=correlation_id,
        )
        await self.repo.agregar(incidente)
        await self.session.commit()
        await self.session.refresh(incidente)

        log.info("incidente.registrado", id=str(incidente.id), incidente_id=datos.incidente_id)
        return incidente

    async def cerrar(
        self, incidente_origen_id: str, *, estado_nuevo: str | None, cerrado_at: datetime | None
    ) -> IncidenteVial | None:
        """Close an incident when Emergencies says it is over.

        A state we do not recognise leaves it open on purpose: closing on a
        word we are not sure about would silently stop relating claims that are
        still caused by a street that is still cut.
        """
        if (estado_nuevo or "").strip().upper() not in ESTADOS_CERRADOS:
            return None

        incidente = await self.repo.obtener_por_origen(incidente_origen_id)
        if incidente is None or incidente.fin is not None:
            return None

        incidente.fin = cerrado_at or datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(incidente)
        log.info(
            "incidente.cerrado",
            id=str(incidente.id),
            incidente_id=incidente_origen_id,
            estado=estado_nuevo,
        )
        return incidente

    async def abierto_cerca(
        self, latitud: float, longitud: float, *, momento: datetime | None = None
    ) -> IncidenteVial | None:
        """The open incident a claim filed here and now is caused by, if any.

        Within the cause radius; with two in range, the closest one. Does not
        commit: it runs inside the claim's own transaction.
        """
        cfg = self.cfg
        momento = momento or datetime.now(UTC)
        radio = float(cfg.incidente_causa_radio_metros)
        candidatos = await self.repo.abiertos(
            momento=momento,
            inicio_desde=momento - timedelta(hours=cfg.incidente_vigencia_horas),
            caja=geo.caja_alrededor(latitud, longitud, radio),
        )

        cercanos: list[tuple[float, IncidenteVial]] = []
        for incidente in candidatos:
            distancia = geo.distancia_metros(
                latitud, longitud, incidente.latitud, incidente.longitud
            )
            if distancia <= radio:
                cercanos.append((distancia, incidente))
        if not cercanos:
            return None
        return min(cercanos, key=lambda par: par[0])[1]
