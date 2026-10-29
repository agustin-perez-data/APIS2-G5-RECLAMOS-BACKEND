"""Tests for the reactions to events published by other modules.

They exercise the handlers directly with realistic payloads: no broker needed,
which is what keeps this suite runnable in CI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.domain.enums import CanalOrigen, CategoriaReclamo, EstadoReclamo, PrioridadReclamo
from app.events import topics
from app.events.consumer import EventConsumer
from app.events.handlers import (
    manejar_contenedor_desbordado,
    manejar_evento_cultural,
    manejar_incidente_creado,
    manejar_intervencion_finalizada,
)
from app.events.producer import InMemoryEventPublisher
from app.repositories.reclamo_repository import FiltroReclamos
from app.schemas.reclamo import ReclamoCrear
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID, evento_contenedor_desbordado


def evento_incidente(**data) -> dict:
    payload = {
        "incidente_id": "INC-77",
        "tipo": "incendio",
        "severidad": "alta",
        "barrio": "Centro",
    }
    payload.update(data)
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": topics.EMERGENCIAS_INCIDENTE_CREADO,
        "occurred_at": datetime.now(UTC).isoformat(),
        "source": "emergencias",
        "data": payload,
    }


# --- residuos.contenedor.desbordado -----------------------------------------
async def test_un_contenedor_desbordado_abre_un_reclamo(
    service: ReclamoService, publisher: InMemoryEventPublisher
) -> None:
    await manejar_contenedor_desbordado(evento_contenedor_desbordado(), service)

    items, total = await service.listar(FiltroReclamos())
    assert total == 1

    reclamo = items[0]
    assert reclamo.categoria is CategoriaReclamo.RESIDUOS
    assert reclamo.canal is CanalOrigen.EVENTO
    # 98.5% full: above the 95% line, so it comes in as high priority.
    assert reclamo.prioridad is PrioridadReclamo.ALTA
    assert reclamo.barrio == "Centro"
    assert reclamo.correlation_id == "corr-residuos-1"

    # A claim born from an event still announces itself on the bus.
    assert topics.RECLAMO_CREADO in publisher.topics


async def test_el_mismo_evento_dos_veces_no_duplica(service: ReclamoService) -> None:
    evento = evento_contenedor_desbordado()

    await manejar_contenedor_desbordado(evento, service)
    await manejar_contenedor_desbordado(evento, service)

    _, total = await service.listar(FiltroReclamos())
    assert total == 1


async def test_contenedor_medio_lleno_entra_con_prioridad_media(
    service: ReclamoService,
) -> None:
    evento = evento_contenedor_desbordado()
    evento["data"]["nivel_llenado"] = 80

    await manejar_contenedor_desbordado(evento, service)

    items, _ = await service.listar(FiltroReclamos())
    assert items[0].prioridad is PrioridadReclamo.MEDIA


async def test_evento_sin_el_campo_obligatorio_falla(service: ReclamoService) -> None:
    evento = evento_contenedor_desbordado()
    del evento["data"]["contenedor_id"]

    with pytest.raises(ValidationError):
        await manejar_contenedor_desbordado(evento, service)


# --- emergencias.incidente.creado -------------------------------------------
async def test_un_incidente_escala_los_reclamos_abiertos_del_barrio(
    service: ReclamoService,
) -> None:
    en_zona = await service.crear(
        ReclamoCrear(
            titulo="Ruidos molestos del bar",
            descripcion="Musica a todo volumen todos los fines de semana hasta tarde",
            categoria=CategoriaReclamo.RUIDOS,
            prioridad=PrioridadReclamo.BAJA,
            barrio="Centro",
        ),
        CIUDADANO_ID,
    )
    fuera_de_zona = await service.crear(
        ReclamoCrear(
            titulo="Ruidos molestos del taller",
            descripcion="Trabajan con amoladora de madrugada y no se puede dormir",
            categoria=CategoriaReclamo.RUIDOS,
            prioridad=PrioridadReclamo.BAJA,
            barrio="Norte",
        ),
        CIUDADANO_ID,
    )

    await manejar_incidente_creado(evento_incidente(), service)

    assert (await service.obtener(en_zona.id)).prioridad is PrioridadReclamo.CRITICA
    assert (await service.obtener(fuera_de_zona.id)).prioridad is PrioridadReclamo.BAJA

    # The escalation is explained to the citizen with an official comment.
    comentarios = await service.repo.comentarios_de(en_zona.id)
    assert len(comentarios) == 1
    assert comentarios[0].es_oficial


async def test_un_incidente_no_toca_los_reclamos_cerrados(
    service: ReclamoService, usuario_operador
) -> None:
    from app.schemas.reclamo import CambioEstado

    reclamo = await service.crear(
        ReclamoCrear(
            titulo="Ruidos molestos del bar",
            descripcion="Musica a todo volumen todos los fines de semana hasta tarde",
            categoria=CategoriaReclamo.RUIDOS,
            prioridad=PrioridadReclamo.BAJA,
            barrio="Centro",
        ),
        CIUDADANO_ID,
    )
    await service.cambiar_estado(
        reclamo.id,
        CambioEstado(estado=EstadoReclamo.RECHAZADO, motivo="sin datos suficientes"),
        usuario_operador,
    )

    await manejar_incidente_creado(evento_incidente(), service)

    assert (await service.obtener(reclamo.id)).prioridad is PrioridadReclamo.BAJA


async def test_incidente_sin_barrio_no_hace_nada(service: ReclamoService) -> None:
    await manejar_incidente_creado(evento_incidente(barrio=None), service)

    _, total = await service.listar(FiltroReclamos())
    assert total == 0


# --- Consumer ----------------------------------------------------------------
def evento_cultural(**data) -> dict:
    payload = {
        "evento_id": "EV-10",
        "titulo": "Feria de la plaza",
        "zona": "Centro",
        "inicio": datetime.now(UTC).isoformat(),
        "cupo_maximo": 300,
        "estado": "ACTIVE",
    }
    payload.update(data)
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": topics.ESPACIOS_EVENTO_PUBLICADO,
        "occurred_at": datetime.now(UTC).isoformat(),
        "source": "espacios",
        "data": payload,
    }


async def _reclamo_en(service: ReclamoService, barrio: str) -> uuid.UUID:
    reclamo = await service.crear(
        ReclamoCrear(
            titulo="Ruidos molestos del bar",
            descripcion="Musica a todo volumen todos los fines de semana hasta tarde",
            categoria=CategoriaReclamo.RUIDOS,
            prioridad=PrioridadReclamo.BAJA,
            barrio=barrio,
        ),
        CIUDADANO_ID,
    )
    return reclamo.id


async def test_una_emergencia_de_prioridad_baja_no_escala(service: ReclamoService) -> None:
    # Emergencies now reports priority in Spanish. Without "baja" in the map it
    # fell back to ALTA, so a minor emergency raised the whole neighbourhood.
    reclamo_id = await _reclamo_en(service, "Centro")

    await manejar_incidente_creado(evento_incidente(severidad="baja"), service)

    assert (await service.obtener(reclamo_id)).prioridad is PrioridadReclamo.BAJA


async def test_una_emergencia_que_no_corta_la_circulacion_no_escala(
    service: ReclamoService,
) -> None:
    # A medical emergency concerns one person, not the area's claims.
    reclamo_id = await _reclamo_en(service, "Centro")

    await manejar_incidente_creado(
        evento_incidente(tipo="medica", afectaCirculacion=False), service
    )

    assert (await service.obtener(reclamo_id)).prioridad is PrioridadReclamo.BAJA


async def test_el_barrio_se_compara_sin_distinguir_mayusculas(service: ReclamoService) -> None:
    # Other modules send the area however they store it; an exact comparison
    # silently escalated nothing.
    reclamo_id = await _reclamo_en(service, "Centro")

    await manejar_incidente_creado(evento_incidente(barrio="CENTRO"), service)

    assert (await service.obtener(reclamo_id)).prioridad is PrioridadReclamo.CRITICA


async def test_un_evento_cultural_cancelado_no_escala(service: ReclamoService) -> None:
    reclamo_id = await _reclamo_en(service, "Centro")

    await manejar_evento_cultural(evento_cultural(estado="CANCELLED"), service)

    assert (await service.obtener(reclamo_id)).prioridad is PrioridadReclamo.BAJA


async def test_un_evento_cultural_masivo_escala_los_reclamos_de_la_zona(
    service: ReclamoService,
) -> None:
    reclamo_id = await _reclamo_en(service, "Centro")

    await manejar_evento_cultural(evento_cultural(), service)

    assert (await service.obtener(reclamo_id)).prioridad is PrioridadReclamo.MEDIA


# --- Espacios Publicos finishing the job in the street -------------------------
def evento_intervencion(reclamo_id, **data) -> dict:
    payload = {
        "reclamoId": str(reclamo_id),
        "resultado": "RESUELTO",
        "idAuto": "AB123CD",
        "solicitadoAt": 1792346000000,
        "resueltoAt": 1792349999000,
    }
    payload.update(data)
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": topics.ESPACIOS_INTERVENCION_FINALIZADA,
        "occurred_at": datetime.now(UTC).isoformat(),
        "source": "espacios",
        "data": payload,
    }


async def test_una_intervencion_resuelta_cierra_un_reclamo_recien_creado(
    service: ReclamoService,
) -> None:
    # The claim never went through our own ASIGNADO/EN_PROCESO: Public Spaces
    # did the work, so it jumps straight to RESUELTO.
    reclamo_id = await _reclamo_en(service, "Palermo")

    await manejar_intervencion_finalizada(evento_intervencion(reclamo_id), service)

    actualizado = await service.obtener(reclamo_id)
    assert actualizado.estado is EstadoReclamo.RESUELTO
    assert actualizado.resuelto_at is not None
    # The citizen has to read something, not an empty field.
    assert actualizado.resolucion


async def test_una_intervencion_rechazada_manda_el_reclamo_a_rechazado(
    service: ReclamoService,
) -> None:
    # "No hacia falta grua" is not the same as "se resolvio": if nobody did
    # anything, telling the neighbour it was solved would be a lie.
    reclamo_id = await _reclamo_en(service, "Palermo")

    await manejar_intervencion_finalizada(
        evento_intervencion(reclamo_id, resultado="RECHAZADO"), service
    )

    actualizado = await service.obtener(reclamo_id)
    assert actualizado.estado is EstadoReclamo.RECHAZADO
    assert actualizado.resuelto_at is None


async def test_la_intervencion_resuelta_publica_el_evento_de_resolucion(
    service: ReclamoService, publisher: InMemoryEventPublisher
) -> None:
    reclamo_id = await _reclamo_en(service, "Palermo")

    await manejar_intervencion_finalizada(evento_intervencion(reclamo_id), service)

    [resuelto] = publisher.eventos_de(topics.RECLAMO_RESUELTO)
    assert resuelto.data.reclamo_id == reclamo_id
    assert resuelto.data.horas_hasta_resolucion >= 0


async def test_la_misma_intervencion_reentregada_no_duplica_nada(
    service: ReclamoService, publisher: InMemoryEventPublisher
) -> None:
    # The gateway delivers at-least-once.
    reclamo_id = await _reclamo_en(service, "Palermo")
    evento = evento_intervencion(reclamo_id)

    await manejar_intervencion_finalizada(evento, service)
    await manejar_intervencion_finalizada(evento, service)

    assert len(publisher.eventos_de(topics.RECLAMO_RESUELTO)) == 1


async def test_una_intervencion_sobre_un_reclamo_cerrado_no_lo_toca(
    service: ReclamoService, usuario_operador
) -> None:
    from app.schemas.reclamo import CambioEstado

    reclamo_id = await _reclamo_en(service, "Palermo")
    await service.cambiar_estado(
        reclamo_id, CambioEstado(estado=EstadoReclamo.RECHAZADO), usuario_operador
    )

    await manejar_intervencion_finalizada(evento_intervencion(reclamo_id), service)

    assert (await service.obtener(reclamo_id)).estado is EstadoReclamo.RECHAZADO


async def test_una_intervencion_sobre_un_reclamo_inexistente_no_falla(
    service: ReclamoService,
) -> None:
    # A claim of another module, or one we deleted: ignoring it beats a 500
    # that makes the gateway retry forever.
    await manejar_intervencion_finalizada(evento_intervencion(uuid.uuid4()), service)


async def test_el_consumer_ignora_topics_sin_handler(
    publisher: InMemoryEventPublisher,
) -> None:
    consumer = EventConsumer(publisher, handlers={}, cfg=settings)

    # Must not raise: an unknown topic is logged and skipped.
    await consumer.procesar("modulo.desconocido.evento", {"data": {}})
    assert publisher.publicados == []


async def test_el_consumer_declara_los_topics_que_escucha(
    publisher: InMemoryEventPublisher,
) -> None:
    consumer = EventConsumer(publisher)

    assert topics.RESIDUOS_CONTENEDOR_DESBORDADO in consumer.topics
    assert topics.EMERGENCIAS_INCIDENTE_CREADO in consumer.topics


async def test_un_mensaje_roto_va_a_la_dlq(publisher: InMemoryEventPublisher) -> None:
    consumer = EventConsumer(publisher)

    await consumer._a_dlq("residuos.contenedor.desbordado", {"roto": True}, ValueError("boom"))

    fallidos = publisher.eventos_de(topics.DLQ)
    assert len(fallidos) == 1
    assert fallidos[0].data.topic_original == "residuos.contenedor.desbordado"
