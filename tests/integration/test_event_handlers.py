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
from app.events.handlers import manejar_contenedor_desbordado, manejar_incidente_creado
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
