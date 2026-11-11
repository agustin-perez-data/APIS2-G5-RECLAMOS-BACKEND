"""Reactions to events published by other CityPass+ modules.

Each handler translates somebody else's event into one of our use cases. The
rule is that a handler never touches the database directly: it always goes
through `ReclamoService`, so a claim born from an event goes through exactly the
same validations and publishes the same events as one filed from the app.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.domain.enums import CategoriaReclamo, NivelCriticidad, PrioridadReclamo
from app.events import topics
from app.events.contracts import (
    ActividadCreada,
    ActividadModificada,
    ContenedorDesbordado,
    CriticidadClimaticaAplicada,
    CriticidadClimaticaConfirmada,
    CriticidadClimaticaFinalizada,
    CriticidadClimaticaLevantada,
    EventoCulturalPublicado,
    IncidenteActualizado,
    IncidenteCreado,
    IntervencionFinalizada,
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

    # ADR 0017: keep the incident so the claims filed next to it from now on can
    # point at it. Only the ones that cut circulation and carry a position are
    # stored; the service decides and is idempotent on redelivery.
    incidente = await service.incidentes.registrar(
        datos,
        recibido_at=evento.occurred_at,
        correlation_id=evento.correlation_id,
    )
    if incidente is not None:
        log.info(
            "handler.incidente_creado.registrado",
            id=str(incidente.id),
            incidente_id=datos.incidente_id,
        )

    prioridad_minima = _SEVERIDAD_A_PRIORIDAD.get(severidad, PrioridadReclamo.ALTA)
    afectados = await service.escalar_por_incidente(
        barrio=datos.barrio,
        prioridad_minima=prioridad_minima,
        # Used only when the incident arrives without a neighbourhood, which the
        # schema they registered allows: there, `barrio` lives inside `ubicacion`
        # and may simply not be filled.
        latitud=datos.latitud,
        longitud=datos.longitud,
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


async def manejar_intervencion_finalizada(raw: dict[str, Any], service: ReclamoService) -> None:
    """`com.citypass.espacios.IntervencionFinalizada` -> close the claim.

    The last link of CU-INT-01: the neighbour reports, we route it, Public
    Spaces does the work in the street and tells us how it ended. `resultado`
    is what decides whether the claim is resolved or was never taken, which is
    the difference between telling the neighbour the truth or not.
    """
    evento = parse_envelope(raw, IntervencionFinalizada)
    datos = evento.data

    reclamo = await service.finalizar_por_intervencion(datos.reclamo_id, datos.resultado)
    if reclamo is None:
        return

    log.info(
        "handler.intervencion_finalizada.reclamo_cerrado",
        reclamo_id=str(reclamo.id),
        resultado=datos.resultado.value,
        estado=reclamo.estado.value,
    )


async def manejar_incidente_actualizado(raw: dict[str, Any], service: ReclamoService) -> None:
    """`emergencias.incidente.actualizado` -> close the incident when it ends.

    Only the closing matters to us: while an incident is open, a claim filed
    next to it is caused by it (ADR 0017), and that has to stop when the street
    is cleared. The intermediate states are Emergencies' business.

    A state we do not recognise as final leaves the incident open on purpose --
    closing on a word we are unsure about would silently stop relating claims
    that are still caused by a street that is still cut. The configured
    `incidente_vigencia_horas` closes it anyway if the event never arrives.
    """
    evento = parse_envelope(raw, IncidenteActualizado)
    datos = evento.data

    incidente = await service.incidentes.cerrar(
        datos.incidente_id,
        estado_nuevo=datos.estado_nuevo,
        cerrado_at=datos.resuelto_at,
    )
    if incidente is None:
        return

    log.info(
        "handler.incidente_actualizado.cerrado",
        id=str(incidente.id),
        incidente_id=datos.incidente_id,
        estado=datos.estado_nuevo,
    )


async def manejar_actividad_creada(raw: dict[str, Any], service: ReclamoService) -> None:
    """`com.citypass.espacios.ActividadCreada` -> remember the mass activity.

    Squad 3, "smart collection after a mass event": nothing changes on arrival.
    The activity is stored so that the claims filed around it from its start
    until a few hours after its end get related to it (ADR 0013). Idempotent:
    a redelivery finds the activity already stored and does nothing.
    """
    evento = parse_envelope(raw, ActividadCreada)
    actividad = await service.actividades.registrar(
        evento.data,
        recibida_at=evento.occurred_at,
        correlation_id=evento.correlation_id,
    )
    if actividad is None:
        return

    log.info(
        "handler.actividad_creada.registrada",
        id=str(actividad.id),
        actividad_id=evento.data.actividad_id,
    )


async def manejar_actividad_modificada(raw: dict[str, Any], service: ReclamoService) -> None:
    """`com.citypass.espacios.ActividadModificada` -> move the activity's state.

    Squad 3 (ADR 0018): a cancelled or suspended activity stops relating the
    claims filed around it, and one back in PROGRAMADA resumes. No claim
    changes here: the ones already related keep their relation, because they
    were filed while the activity was on. Idempotent on redelivery.
    """
    evento = parse_envelope(raw, ActividadModificada)
    actividad = await service.actividades.cambiar_estado(
        evento.data,
        recibida_at=evento.occurred_at,
        correlation_id=evento.correlation_id,
    )
    if actividad is None:
        return

    log.info(
        "handler.actividad_modificada.aplicada",
        id=str(actividad.id),
        actividad_id=actividad.actividad_origen_id,
        estado=actividad.estado,
    )


def _acciones_de(nivel: NivelCriticidad) -> list[str]:
    """What the level actually did, for the summary event."""
    acciones = ["MARCA_RECLAMOS", "AVISO_CIUDADANOS"]
    if nivel in (NivelCriticidad.ALTA, NivelCriticidad.CRITICA):
        acciones.append("AJUSTE_PRIORIDAD")
    return acciones


async def _descartar_si_repetido(raw: dict, service: ReclamoService, tipo: str) -> bool:
    """True when this event id was already handled and there is nothing to do.

    The bus delivers at least once and a redelivered confirmation would notify
    every affected neighbour a second time, so this guard runs before any work.
    """
    event_id = str(raw.get("event_id") or "")
    if not event_id:
        return False
    if await service.clima.ya_procesado(event_id):
        log.info("handler.clima.evento_repetido", event_id=event_id, tipo=tipo)
        return True
    # Written before the work, inside the same transaction: if the handler
    # fails, the rollback takes this with it and the retry is processed.
    await service.clima.marcar_procesado(event_id, tipo)
    return False


async def manejar_criticidad_confirmada(raw: dict[str, Any], service: ReclamoService) -> None:
    """`com.citypass.espacios.CriticidadClimaticaConfirmada` -> record the alert.

    Step 2 only stores it and keeps its order straight. Marking the claims in
    the area and moving their priority is step 3.
    """
    if await _descartar_si_repetido(raw, service, topics.ESPACIOS_CLIMA_CONFIRMADA):
        return

    evento = parse_envelope(raw, CriticidadClimaticaConfirmada)
    alerta = await service.clima.registrar_confirmada(evento.data, occurred_at=evento.occurred_at)
    if alerta is None:
        # Older than what we already applied: their event carries no version,
        # so the bus' timestamp is the only ordering available.
        log.info("handler.clima.evento_viejo", alerta_id=str(evento.data.alerta_id))
        return

    await service.session.commit()
    log.info(
        "handler.clima.alerta_registrada",
        alerta_id=str(alerta.alerta_id),
        nivel=alerta.nivel.value,
        barrios=len(alerta.barrios),
        ubicaciones=len(alerta.ubicaciones),
    )

    # Stage 1: mark the claims already open in the area and tell their owners.
    resumen = await service.escalar_por_alerta_climatica(alerta)
    log.info(
        "handler.clima.reclamos_marcados",
        alerta_id=str(alerta.alerta_id),
        marcados=resumen.marcados,
        sin_ubicacion=resumen.sin_ubicacion,
        por_barrio=resumen.por_barrio,
    )

    # Published after the commit (ADR 0004). Public Spaces uses it to confirm
    # the alert landed, Analytics to size the event.
    await service.publisher.publish(
        topics.CLIMA_APLICADA,
        CriticidadClimaticaAplicada(
            alerta_id=alerta.alerta_id,
            nivel_criticidad=alerta.nivel,
            acciones_aplicadas=_acciones_de(alerta.nivel),
            reclamos_marcados=resumen.marcados,
            reclamos_sin_ubicacion=resumen.sin_ubicacion,
            avisos_enviados=resumen.avisos_enviados,
        ),
        key=str(alerta.alerta_id),
    )


async def manejar_criticidad_finalizada(raw: dict[str, Any], service: ReclamoService) -> None:
    """`com.citypass.espacios.CriticidadClimaticaFinalizada` -> close the alert."""
    if await _descartar_si_repetido(raw, service, topics.ESPACIOS_CLIMA_FINALIZADA):
        return

    evento = parse_envelope(raw, CriticidadClimaticaFinalizada)
    alerta = await service.clima.registrar_finalizada(evento.data, occurred_at=evento.occurred_at)
    if alerta is None:
        # Unknown alert or a stale event. Not an error: Public Spaces can close
        # an alert whose confirmation never reached us.
        log.info("handler.clima.finalizada_ignorada", alerta_id=str(evento.data.alerta_id))
        await service.session.commit()
        return

    await service.session.commit()

    # Stage 3: tell the neighbours the alert is over and count what it left.
    resumen = await service.cerrar_alerta_climatica(alerta)
    log.info(
        "handler.clima.alerta_finalizada",
        alerta_id=str(alerta.alerta_id),
        marcados=resumen.marcados,
        abiertos=resumen.abiertos_al_finalizar,
        duplicados=resumen.duplicados_detectados,
    )

    await service.publisher.publish(
        topics.CLIMA_LEVANTADA,
        CriticidadClimaticaLevantada(
            alerta_id=alerta.alerta_id,
            levantada_en=datetime.now(UTC),
            reclamos_abiertos_al_confirmar=resumen.marcados,
            # Claims filed while the alert was live: the ones it carries minus
            # the ones that were already open when it was confirmed.
            reclamos_creados_durante=resumen.creados_durante,
            subidos_de_prioridad=resumen.subidos_de_prioridad,
            duplicados_detectados=resumen.duplicados_detectados,
            abiertos_al_finalizar=resumen.abiertos_al_finalizar,
            sin_ubicacion=resumen.sin_ubicacion,
        ),
        key=str(alerta.alerta_id),
    )


HANDLERS: dict[str, Handler] = {
    topics.RESIDUOS_CONTENEDOR_DESBORDADO: manejar_contenedor_desbordado,
    topics.EMERGENCIAS_INCIDENTE_CREADO: manejar_incidente_creado,
    topics.EMERGENCIAS_INCIDENTE_ACTUALIZADO: manejar_incidente_actualizado,
    topics.ESPACIOS_EVENTO_PUBLICADO: manejar_evento_cultural,
    topics.ESPACIOS_INTERVENCION_FINALIZADA: manejar_intervencion_finalizada,
    topics.ESPACIOS_CLIMA_CONFIRMADA: manejar_criticidad_confirmada,
    topics.ESPACIOS_CLIMA_FINALIZADA: manejar_criticidad_finalizada,
    topics.ESPACIOS_ACTIVIDAD_CREADA: manejar_actividad_creada,
    topics.ESPACIOS_ACTIVIDAD_MODIFICADA: manejar_actividad_modificada,
}
