"""Mass activities and the claims filed around them (squad 3, ADR 0013).

Public Spaces announces an activity with `ActividadCreada`. From then on, every
claim filed close to it, between its start and a few hours after its end, is
related to it: once a festival is over, the overflowing bins and the noise
complaints in that square are part of the same event, not isolated reports.

`registrar` runs from the event handler and owns its transaction.
`en_curso_cerca` runs inside `ReclamoService.crear`, before the claim's commit,
so the claim and its relation are saved together or not at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.db.models import ActividadMasiva
from app.domain import geo
from app.events.contracts import ActividadCreada
from app.repositories.actividad_repository import ActividadRepository

log = get_logger(__name__)

# What Public Spaces may send for a cancelled activity, in either language.
ESTADOS_CANCELADOS = frozenset({"CANCELADA", "CANCELADO", "CANCELLED"})


class ActividadService:
    def __init__(self, session: AsyncSession, cfg: Settings | None = None) -> None:
        self.session = session
        self.repo = ActividadRepository(session)
        self.cfg = cfg or settings

    async def registrar(
        self,
        datos: ActividadCreada,
        *,
        recibida_at: datetime,
        correlation_id: str | None = None,
    ) -> ActividadMasiva | None:
        """Keep a mass activity, or return None when there is nothing to keep.

        Ignored: cancelled activities, activities below the mass cut, and
        activities without coordinates, which could not relate anything.
        Returning None for an activity already stored is what makes a
        redelivery harmless: the gateway is at-least-once.
        """
        if (datos.estado or "").upper() in ESTADOS_CANCELADOS:
            log.info("actividad.ignorada", actividad_id=datos.actividad_id, motivo="cancelada")
            return None
        if (datos.capacidad or 0) < self.cfg.actividad_masiva_capacidad_minima:
            log.info(
                "actividad.ignorada",
                actividad_id=datos.actividad_id,
                motivo="no_es_masiva",
                capacidad=datos.capacidad,
            )
            return None
        if datos.ubicacion is None:
            log.warning(
                "actividad.ignorada", actividad_id=datos.actividad_id, motivo="sin_coordenadas"
            )
            return None

        existente = await self.repo.obtener_por_origen(datos.actividad_id)
        if existente is not None:
            log.info(
                "actividad.ya_registrada",
                actividad_id=datos.actividad_id,
                id=str(existente.id),
            )
            return None

        actividad = ActividadMasiva(
            actividad_origen_id=datos.actividad_id,
            titulo=datos.titulo[:150],
            capacidad=datos.capacidad or 0,
            latitud=datos.ubicacion.lat,
            longitud=datos.ubicacion.lng,
            direccion=datos.direccion[:255] if datos.direccion else None,
            espacio_nombre=datos.espacio_nombre[:150] if datos.espacio_nombre else None,
            # Without a start, the activity counts from the moment we heard of it.
            inicio=datos.inicio or recibida_at,
            fin=datos.fin,
            correlation_id=correlation_id,
        )
        await self.repo.agregar(actividad)
        await self.session.commit()
        await self.session.refresh(actividad)

        log.info(
            "actividad.registrada",
            id=str(actividad.id),
            actividad_id=datos.actividad_id,
            capacidad=actividad.capacidad,
        )
        return actividad

    async def en_curso_cerca(
        self, latitud: float, longitud: float, *, momento: datetime | None = None
    ) -> ActividadMasiva | None:
        """The mass activity a claim filed here and now belongs to, if any.

        In course means started, and ended no more than the configured hours
        ago. Within the radius; with two activities in range, the closest one.
        Does not commit: it runs inside the claim's own transaction.
        """
        cfg = self.cfg
        momento = momento or datetime.now(UTC)
        candidatas = await self.repo.en_curso(
            momento=momento,
            fin_desde=momento - timedelta(hours=cfg.actividad_masiva_horas_despues),
            caja=geo.caja_alrededor(latitud, longitud, cfg.actividad_masiva_radio_metros),
        )

        cercanas: list[tuple[float, ActividadMasiva]] = []
        for actividad in candidatas:
            distancia = geo.distancia_metros(
                latitud, longitud, actividad.latitud, actividad.longitud
            )
            if distancia <= cfg.actividad_masiva_radio_metros:
                cercanas.append((distancia, actividad))
        if not cercanas:
            return None
        return min(cercanas, key=lambda par: par[0])[1]

    async def listar(
        self, *, incluir_finalizadas: bool = False
    ) -> list[tuple[ActividadMasiva, int]]:
        """Activities with how many claims each has related, by start time.

        By default only the ones still relating claims or about to: those whose
        end plus the window has not passed yet.
        """
        fin_desde = (
            None
            if incluir_finalizadas
            else datetime.now(UTC) - timedelta(hours=self.cfg.actividad_masiva_horas_despues)
        )
        actividades = await self.repo.listar(fin_desde=fin_desde)
        conteos: dict[uuid.UUID, int] = await self.repo.reclamos_por_actividad(
            [a.id for a in actividades]
        )
        return [(actividad, conteos.get(actividad.id, 0)) for actividad in actividades]
