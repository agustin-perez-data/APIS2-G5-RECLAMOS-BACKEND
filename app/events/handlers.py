"""Reactions to events published by other CityPass+ modules.

Each handler translates somebody else's event into one of our use cases. The
rule is that a handler never touches the database directly: it always goes
through `ReclamoService`, so a claim born from an event goes through exactly the
same validations and publishes the same events as one filed from the app.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.logging import get_logger
from app.domain.enums import CategoriaReclamo, PrioridadReclamo
from app.events import topics
from app.events.contracts import (
    ContenedorDesbordado,
    EventoCulturalPublicado,
    IncidenteCreado,
    parse_envelope,
)
from app.schemas.reclamo import ReclamoCrear
from app.services.reclamo_service import ReclamoService

log = get_logger(__name__)

Handler = Callable[[dict[str, Any], ReclamoService], Awaitable[None]]

# Maps the severity reported by Emergencies onto our internal priority.
_SEVERIDAD_A_PRIORIDAD: dict[str, PrioridadReclamo] = {
    "critica": PrioridadReclamo.CRITICA,
    "critical": PrioridadReclamo.CRITICA,
    "alta": PrioridadReclamo.CRITICA,
    "high": PrioridadReclamo.CRITICA,
    "media": PrioridadReclamo.ALTA,
    "medium": PrioridadReclamo.ALTA,
}

# Reported severities that do not justify reordering the area's claims.
_SEVERIDADES_QUE_NO_ESCALAN = frozenset({"baja", "low", "menor", "minor"})


async def manejar_contenedor_desbordado(raw: dict[str, Any], service: ReclamoService) -> None:
    """`residuos.contenedor.desbordado` -> file a claim automatically.

    When a sensor from the Waste module detects an overflowing container, no
    neighbour should have to report it: the claim opens by itself and lands in
    the same inbox as every other one.
    """
    evento = parse_envelope(raw, ContenedorDesbordado)
    datos = evento.data

    nivel = f" (nivel de llenado: {datos.nivel_llenado}%)" if datos.nivel_llenado else ""
    ubicacion = datos.direccion or datos.barrio or "ubicacion informada por el sensor"

    reclamo = await service.crear_desde_evento(
        ReclamoCrear(
            titulo=f"Contenedor desbordado en {ubicacion}"[:150],
            descripcion=(
                f"Alta automatica a partir del sensor del contenedor {datos.contenedor_id}"
                f"{nivel}. Origen: modulo de Gestion de Residuos."
            ),
            categoria=CategoriaReclamo.RESIDUOS,
            prioridad=(
                PrioridadReclamo.ALTA
                if (datos.nivel_llenado or 0) >= 95
                else PrioridadReclamo.MEDIA
            ),
            direccion=datos.direccion,
            barrio=datos.barrio,
            latitud=datos.latitud,
            longitud=datos.longitud,
        ),
        evento_id=str(evento.event_id),
        correlation_id=evento.correlation_id or str(evento.event_id),
    )

    if reclamo is not None:
        log.info(
            "handler.contenedor_desbordado.reclamo_creado",
            reclamo_id=str(reclamo.id),
            contenedor_id=datos.contenedor_id,
        )


async def manejar_incidente_creado(raw: dict[str, Any], service: ReclamoService) -> None:
    """`emergencias.incidente.creado` -> re-prioritise the affected area.

    While an emergency is active in a neighbourhood, open claims from that area
    stop competing for priority with the rest of the city.
    """
    evento = parse_envelope(raw, IncidenteCreado)
    datos = evento.data

    # CU-INT-01: only incidents that cut circulation reorder the area's claims.
    # A medical emergency concerns one person, not the neighbourhood's potholes.
    if datos.afecta_circulacion is False:
        return

    severidad = (datos.severidad or "").lower()
    # Without this, an unmapped severity falls back to ALTA and a minor
    # emergency raises the whole neighbourhood.
    if severidad in _SEVERIDADES_QUE_NO_ESCALAN:
        return

    prioridad_minima = _SEVERIDAD_A_PRIORIDAD.get(severidad, PrioridadReclamo.ALTA)
    afectados = await service.escalar_por_incidente(
        barrio=datos.barrio,
        prioridad_minima=prioridad_minima,
        motivo=(
            f"Prioridad elevada automaticamente por un incidente de Emergencias "
            f"({datos.tipo or 'sin tipo'}, incidente {datos.incidente_id}) en la zona."
        ),
    )
    log.info(
        "handler.incidente_creado.reclamos_escalados",
        incidente_id=datos.incidente_id,
        barrio=datos.barrio,
        cantidad=len(afectados),
    )


# Events this large make the area's open claims (a pothole, a fallen tree)
# worth attending before the crowd arrives. Smaller ones change nothing.
CUPO_MINIMO_EVENTO_MASIVO = 100


async def manejar_evento_cultural(raw: dict[str, Any], service: ReclamoService) -> None:
    """`com.citypass.espacios.EventoComunitarioPublicado` -> raise the area's claims.

    CU-INT-01: a large cultural event concentrates people in a known place and
    time. Open claims in that neighbourhood go up to at least MEDIA, with an
    official comment saying why. Like the Emergencies handler, raising is
    idempotent: a redelivery finds the priority already raised and does nothing.
    """
    evento = parse_envelope(raw, EventoCulturalPublicado)
    datos = evento.data

    if (datos.estado or "").upper() == "CANCELLED":
        return

    if (datos.cupo_maximo or 0) < CUPO_MINIMO_EVENTO_MASIVO:
        return

    afectados = await service.escalar_por_incidente(
        barrio=datos.zona,
        prioridad_minima=PrioridadReclamo.MEDIA,
        motivo=(
            f"Prioridad elevada automaticamente: el evento '{datos.titulo}' "
            f"({datos.inicio:%d/%m %H:%M}, cupo {datos.cupo_maximo}) se hace en la zona."
        ),
    )
    log.info(
        "handler.evento_cultural.reclamos_escalados",
        evento_id=datos.evento_id,
        zona=datos.zona,
        cantidad=len(afectados),
    )


HANDLERS: dict[str, Handler] = {
    topics.RESIDUOS_CONTENEDOR_DESBORDADO: manejar_contenedor_desbordado,
    topics.EMERGENCIAS_INCIDENTE_CREADO: manejar_incidente_creado,
    topics.ESPACIOS_EVENTO_PUBLICADO: manejar_evento_cultural,
}
