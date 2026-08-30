"""Use-case tests: business rules plus the events each one publishes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.core.exceptions import (
    AdhesionDelAutor,
    AdhesionDuplicada,
    ReclamoCerrado,
    ReclamoNoEncontrado,
    TransicionInvalida,
)
from app.domain.enums import (
    CanalOrigen,
    CategoriaReclamo,
    EstadoReclamo,
    OrigenClasificacion,
    PrioridadReclamo,
)
from app.events import topics
from app.events.producer import InMemoryEventPublisher
from app.repositories.reclamo_repository import FiltroReclamos
from app.schemas.reclamo import CambioEstado, ReclamoCrear
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID, OTRO_CIUDADANO_ID


def datos_reclamo(**overrides) -> ReclamoCrear:
    base = {
        "titulo": "Luminaria apagada en la plaza",
        "descripcion": "El foco del poste no enciende hace dos semanas y quedo todo oscuro",
        "barrio": "Centro",
    }
    base.update(overrides)
    return ReclamoCrear(**base)


async def test_crear_clasifica_y_publica_dos_eventos(
    service: ReclamoService, publisher: InMemoryEventPublisher
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)

    assert reclamo.categoria is CategoriaReclamo.ALUMBRADO
    assert reclamo.origen_clasificacion is OrigenClasificacion.MODELO
    assert reclamo.confianza_clasificacion is not None
    assert reclamo.estado is EstadoReclamo.RECIBIDO
    assert publisher.topics == [topics.RECLAMO_CREADO, topics.RECLAMO_CLASIFICADO]

    creado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert creado.data.reclamo_id == reclamo.id
    assert creado.source == settings.service_source


async def test_si_el_ciudadano_clasifica_no_se_publica_clasificado(
    service: ReclamoService, publisher: InMemoryEventPublisher
) -> None:
    reclamo = await service.crear(
        datos_reclamo(categoria=CategoriaReclamo.BACHES, prioridad=PrioridadReclamo.ALTA),
        CIUDADANO_ID,
    )

    assert reclamo.origen_clasificacion is OrigenClasificacion.CIUDADANO
    assert reclamo.confianza_clasificacion is None
    assert publisher.topics == [topics.RECLAMO_CREADO]


async def test_baja_confianza_manda_el_reclamo_a_revision(
    session, publisher: InMemoryEventPublisher
) -> None:
    # Threshold at 1.0: nothing can clear it, so every claim needs human triage.
    exigente = settings.model_copy(update={"confianza_minima_clasificador": 1.0})
    service = ReclamoService(session, publisher, cfg=exigente)

    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    assert reclamo.estado is EstadoReclamo.EN_REVISION


async def test_el_alta_deja_historial(service: ReclamoService) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    historial = await service.repo.historial_de(reclamo.id)

    assert len(historial) == 1
    assert historial[0].estado_anterior is None
    assert historial[0].estado_nuevo is EstadoReclamo.RECIBIDO


async def test_obtener_inexistente_falla(service: ReclamoService) -> None:
    with pytest.raises(ReclamoNoEncontrado):
        await service.obtener(uuid.uuid4())


# --- State machine -----------------------------------------------------------
async def test_transicion_invalida_es_rechazada(service: ReclamoService, usuario_operador) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)

    with pytest.raises(TransicionInvalida):
        await service.cambiar_estado(
            reclamo.id, CambioEstado(estado=EstadoReclamo.CERRADO), usuario_operador
        )


async def test_flujo_completo_hasta_resuelto_publica_evento_de_resolucion(
    service: ReclamoService, publisher: InMemoryEventPublisher, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)

    for estado in (EstadoReclamo.ASIGNADO, EstadoReclamo.EN_PROCESO, EstadoReclamo.RESUELTO):
        await service.cambiar_estado(
            reclamo.id,
            CambioEstado(estado=estado, motivo=f"paso a {estado.value}", asignado_a="cuadrilla-3"),
            usuario_operador,
        )

    actualizado = await service.obtener(reclamo.id)
    assert actualizado.estado is EstadoReclamo.RESUELTO
    assert actualizado.resuelto_at is not None
    assert actualizado.asignado_a == "cuadrilla-3"

    resueltos = publisher.eventos_de(topics.RECLAMO_RESUELTO)
    assert len(resueltos) == 1
    assert resueltos[0].data.horas_hasta_resolucion >= 0
    assert len(publisher.eventos_de(topics.RECLAMO_ESTADO_CAMBIADO)) == 3

    historial = await service.repo.historial_de(reclamo.id)
    assert len(historial) == 4  # alta + tres cambios


async def test_el_evento_de_estado_lleva_la_key_del_agregado(
    service: ReclamoService, publisher: InMemoryEventPublisher, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.cambiar_estado(
        reclamo.id, CambioEstado(estado=EstadoReclamo.EN_REVISION), usuario_operador
    )

    # Ordering per claim depends on every event sharing the same partition key.
    keys = {key for _, key, _ in publisher.publicados}
    assert keys == {str(reclamo.id)}


# --- Auto-close (US-17) ---------------------------------------------------------
async def test_cierra_reclamos_resueltos_hace_mas_de_7_dias(
    service: ReclamoService, publisher: InMemoryEventPublisher, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    for estado in (EstadoReclamo.ASIGNADO, EstadoReclamo.EN_PROCESO, EstadoReclamo.RESUELTO):
        await service.cambiar_estado(reclamo.id, CambioEstado(estado=estado), usuario_operador)

    # Backdate the resolution past the auto-close window.
    vencido = await service.obtener(reclamo.id)
    vencido.resuelto_at = datetime.now(UTC) - timedelta(days=8)
    await service.session.commit()

    cerrados = await service.cerrar_resueltos_vencidos()

    assert [r.id for r in cerrados] == [reclamo.id]
    actualizado = await service.obtener(reclamo.id)
    assert actualizado.estado is EstadoReclamo.CERRADO
    assert actualizado.cerrado_at is not None

    cambios = publisher.eventos_de(topics.RECLAMO_ESTADO_CAMBIADO)
    assert cambios[-1].data.estado_anterior is EstadoReclamo.RESUELTO
    assert cambios[-1].data.estado_nuevo is EstadoReclamo.CERRADO


async def test_no_cierra_reclamos_resueltos_recientemente(
    service: ReclamoService, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    for estado in (EstadoReclamo.ASIGNADO, EstadoReclamo.EN_PROCESO, EstadoReclamo.RESUELTO):
        await service.cambiar_estado(reclamo.id, CambioEstado(estado=estado), usuario_operador)

    cerrados = await service.cerrar_resueltos_vencidos()

    assert cerrados == []
    actualizado = await service.obtener(reclamo.id)
    assert actualizado.estado is EstadoReclamo.RESUELTO


# --- Comments ----------------------------------------------------------------
async def test_comentario_de_operador_queda_marcado_como_oficial(
    service: ReclamoService, usuario_operador
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    comentario = await service.comentar(reclamo.id, "Ya lo derivamos al area", usuario_operador)

    assert comentario.es_oficial


async def test_no_se_comenta_un_reclamo_cerrado(
    service: ReclamoService, usuario_operador, usuario_ciudadano
) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.cambiar_estado(
        reclamo.id,
        CambioEstado(estado=EstadoReclamo.RECHAZADO, motivo="duplicado"),
        usuario_operador,
    )

    with pytest.raises(ReclamoCerrado):
        await service.comentar(reclamo.id, "hola", usuario_ciudadano)


# --- Citizen support ---------------------------------------------------------
async def test_el_autor_no_puede_adherir_a_su_propio_reclamo(service: ReclamoService) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)

    with pytest.raises(AdhesionDelAutor):
        await service.adherir(reclamo.id, CIUDADANO_ID)


async def test_no_se_puede_adherir_dos_veces(service: ReclamoService) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.adherir(reclamo.id, OTRO_CIUDADANO_ID)

    with pytest.raises(AdhesionDuplicada):
        await service.adherir(reclamo.id, OTRO_CIUDADANO_ID)


async def test_las_adhesiones_escalan_la_prioridad(
    session, publisher: InMemoryEventPublisher
) -> None:
    # Threshold lowered to 2 so the test does not need ten citizens.
    sensible = settings.model_copy(update={"adhesiones_para_escalar": 2})
    service = ReclamoService(session, publisher, cfg=sensible)

    reclamo = await service.crear(
        datos_reclamo(categoria=CategoriaReclamo.RUIDOS, prioridad=PrioridadReclamo.BAJA),
        CIUDADANO_ID,
    )
    await service.adherir(reclamo.id, "vecino-1")
    actualizado = await service.adherir(reclamo.id, "vecino-2")

    assert actualizado.adhesiones_count == 2
    assert actualizado.prioridad is PrioridadReclamo.ALTA

    adhesiones = publisher.eventos_de(topics.RECLAMO_ADHERIDO)
    assert [evento.data.escalado for evento in adhesiones] == [False, True]


# --- Listing and metrics -----------------------------------------------------
async def test_listado_filtra_y_pagina(service: ReclamoService) -> None:
    await service.crear(datos_reclamo(categoria=CategoriaReclamo.BACHES), CIUDADANO_ID)
    await service.crear(datos_reclamo(categoria=CategoriaReclamo.RUIDOS), CIUDADANO_ID)
    await service.crear(datos_reclamo(categoria=CategoriaReclamo.BACHES), OTRO_CIUDADANO_ID)

    items, total = await service.listar(FiltroReclamos(categoria=CategoriaReclamo.BACHES))
    assert total == 2

    items, total = await service.listar(FiltroReclamos(ciudadano_id=OTRO_CIUDADANO_ID))
    assert total == 1

    items, total = await service.listar(FiltroReclamos(), page=1, size=2)
    assert total == 3
    assert len(items) == 2


async def test_busqueda_por_texto_libre(service: ReclamoService) -> None:
    await service.crear(datos_reclamo(titulo="Contenedor desbordado en la esquina"), CIUDADANO_ID)
    await service.crear(datos_reclamo(titulo="Semaforo sin funcionar"), CIUDADANO_ID)

    _, total = await service.listar(FiltroReclamos(texto="contenedor"))
    assert total == 1


async def test_estadisticas(service: ReclamoService, usuario_operador) -> None:
    reclamo = await service.crear(datos_reclamo(), CIUDADANO_ID)
    await service.crear(datos_reclamo(categoria=CategoriaReclamo.BACHES), OTRO_CIUDADANO_ID)

    for estado in (EstadoReclamo.ASIGNADO, EstadoReclamo.EN_PROCESO, EstadoReclamo.RESUELTO):
        await service.cambiar_estado(reclamo.id, CambioEstado(estado=estado), usuario_operador)

    datos = await service.estadisticas()
    assert datos["total"] == 2
    assert dict(datos["por_estado"])[EstadoReclamo.RESUELTO.value] == 1
    assert datos["tiempo_resolucion_horas_promedio"] is not None


# --- Event-driven intake -----------------------------------------------------
async def test_alta_desde_evento_es_idempotente(service: ReclamoService) -> None:
    evento_id = "evt-abc-123"

    primero = await service.crear_desde_evento(datos_reclamo(), evento_id=evento_id)
    segundo = await service.crear_desde_evento(datos_reclamo(), evento_id=evento_id)

    assert primero is not None
    assert primero.canal is CanalOrigen.EVENTO
    assert primero.evento_origen_id == evento_id
    # A redelivery must not create a second claim.
    assert segundo is None
