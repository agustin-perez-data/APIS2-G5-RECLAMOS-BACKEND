"""A5 intake through the existing claim service, without the event handler."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import (
    USUARIO_SISTEMA,
    CanalOrigen,
    CategoriaReclamo,
    OrigenClasificacion,
    PrioridadReclamo,
)
from app.events import topics
from app.events.contracts import EventEnvelope, IncidenteActualizado
from app.events.producer import InMemoryEventPublisher
from app.schemas.reclamo import ReclamoCrear, SugerenciaClasificacion
from app.services.emergencia_via_service import (
    TITULO_RECLAMO_VIAL,
    crear_reclamo_por_emergencia_vial,
)
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID


class ClasificadorConPrioridad:
    nombre = "clasificador-de-prueba"

    def __init__(self, prioridad: PrioridadReclamo) -> None:
        self.prioridad = prioridad
        self.llamadas: list[tuple[str, str]] = []

    def clasificar(self, titulo: str, descripcion: str) -> SugerenciaClasificacion:
        self.llamadas.append((titulo, descripcion))
        return SugerenciaClasificacion(
            categoria=CategoriaReclamo.BACHES,
            prioridad=self.prioridad,
            confianza=0.9,
            evidencia=["calzada"],
            modelo=self.nombre,
        )


async def test_a5_persiste_clasifica_publica_y_no_duplica_por_event_id_distinto(
    service: ReclamoService, session: AsyncSession, publisher: InMemoryEventPublisher
) -> None:
    datos = IncidenteActualizado.model_validate(
        {
            "emergenciaId": "fa4da786-d22b-448b-b174-8b3e1f466247",
            "estadoNuevo": "RESUELTA",
            "causasRelacionadas": ["VIA"],
            "descripcionProblema": "Quedo un pozo profundo en la calzada luego del accidente.",
            "barrio": "Palermo",
            "latitud": -34.589,
            "longitud": -58.431,
            "correlationId": "corr-emergencia-a5",
        }
    )
    primero = EventEnvelope[IncidenteActualizado](
        event_type=topics.EMERGENCIAS_INCIDENTE_ACTUALIZADO,
        correlation_id=datos.correlation_id,
        data=datos,
    )
    segundo = EventEnvelope[IncidenteActualizado](
        event_type=topics.EMERGENCIAS_INCIDENTE_ACTUALIZADO,
        correlation_id=datos.correlation_id,
        data=datos,
    )

    creado = await crear_reclamo_por_emergencia_vial(
        primero.data, service, correlation_id=primero.correlation_id
    )
    duplicado = await crear_reclamo_por_emergencia_vial(
        segundo.data, service, correlation_id=segundo.correlation_id
    )

    assert primero.event_id != segundo.event_id
    assert creado is not None
    assert duplicado is None
    assert creado.ciudadano_id == USUARIO_SISTEMA
    assert creado.titulo == TITULO_RECLAMO_VIAL
    assert creado.descripcion == datos.descripcion_problema
    assert creado.barrio == "Palermo"
    assert creado.latitud == -34.589
    assert creado.longitud == -58.431
    assert creado.canal is CanalOrigen.EVENTO
    assert creado.origen_clasificacion is OrigenClasificacion.MODELO
    assert creado.confianza_clasificacion is not None
    assert creado.evento_origen_id == "emergencia:fa4da786-d22b-448b-b174-8b3e1f466247"
    assert creado.correlation_id == "corr-emergencia-a5"

    session.expunge_all()
    guardado = await service.repo.obtener_por_evento_origen(creado.evento_origen_id)
    assert guardado is not None
    assert guardado.id == creado.id
    assert publisher.topics == [topics.RECLAMO_CREADO, topics.RECLAMO_CLASIFICADO]
    publicado = publisher.eventos_de(topics.RECLAMO_CREADO)[0]
    assert publicado.data.ciudadano_id == USUARIO_SISTEMA
    assert publicado.data.canal == CanalOrigen.EVENTO
    assert publicado.correlation_id == "corr-emergencia-a5"


@pytest.mark.parametrize(
    ("calculada", "final"),
    [
        (PrioridadReclamo.BAJA, PrioridadReclamo.ALTA),
        (PrioridadReclamo.MEDIA, PrioridadReclamo.ALTA),
        (PrioridadReclamo.ALTA, PrioridadReclamo.ALTA),
        (PrioridadReclamo.CRITICA, PrioridadReclamo.CRITICA),
    ],
)
async def test_a5_aplica_prioridad_minima_tras_clasificar(
    session: AsyncSession,
    publisher: InMemoryEventPublisher,
    calculada: PrioridadReclamo,
    final: PrioridadReclamo,
) -> None:
    clasificador = ClasificadorConPrioridad(calculada)
    service = ReclamoService(session, publisher, clasificador=clasificador)
    descripcion = "Quedo una rotura peligrosa en la calzada despues del accidente."
    evento = IncidenteActualizado.model_validate(
        {
            "emergenciaId": "a91c7ef0-93ca-4bde-90f5-d69dd6370a17",
            "estadoNuevo": "RESUELTA",
            "causasRelacionadas": ["VIA"],
            "descripcionProblema": descripcion,
            "latitud": -34.589,
            "longitud": -58.431,
        }
    )

    reclamo = await crear_reclamo_por_emergencia_vial(evento, service)

    assert reclamo is not None
    assert clasificador.llamadas == [(TITULO_RECLAMO_VIAL, descripcion)]
    assert reclamo.categoria is CategoriaReclamo.BACHES
    assert reclamo.origen_clasificacion is OrigenClasificacion.MODELO
    assert reclamo.confianza_clasificacion == 0.9
    assert reclamo.prioridad is final
    assert publisher.eventos_de(topics.RECLAMO_CREADO)[0].data.prioridad is final
    assert publisher.eventos_de(topics.RECLAMO_CLASIFICADO)[0].data.prioridad is final


async def test_el_piso_de_a5_no_afecta_ciudadanos_ni_otros_eventos(
    session: AsyncSession, publisher: InMemoryEventPublisher
) -> None:
    clasificador = ClasificadorConPrioridad(PrioridadReclamo.BAJA)
    service = ReclamoService(session, publisher, clasificador=clasificador)
    datos = ReclamoCrear(
        titulo="Rotura en la calzada",
        descripcion="Hay una rotura visible en la calzada de esta cuadra.",
    )

    ciudadano = await service.crear(datos, CIUDADANO_ID)
    otro_evento = await service.crear_desde_evento(datos, evento_id="otro-evento-1")

    assert ciudadano.prioridad is PrioridadReclamo.BAJA
    assert otro_evento is not None
    assert otro_evento.prioridad is PrioridadReclamo.BAJA
    assert ciudadano.origen_clasificacion is OrigenClasificacion.MODELO
    assert otro_evento.origen_clasificacion is OrigenClasificacion.MODELO
    assert len(clasificador.llamadas) == 2
