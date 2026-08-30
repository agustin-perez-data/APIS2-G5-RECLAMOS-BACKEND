"""Use cases of the claims module.

The business logic lives here: validation, the state machine, escalation by
endorsements and event publication. It knows nothing about FastAPI or Kafka
directly — it talks to the `EventPublisher` port — so it can be tested without
starting either the server or the broker.

A note on publishing: events go out **after** the commit. If the process dies
between the commit and the send, the event is lost. The complete answer is a
transactional outbox; it is recorded as technical debt in
`docs/adr/0004-publicacion-de-eventos.md` because at this scale the cost of
building one is not justified yet.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.exceptions import (
    AdhesionDelAutor,
    AdhesionDuplicada,
    ReclamoCerrado,
    ReclamoNoEncontrado,
    TransicionInvalida,
)
from app.core.logging import get_logger
from app.core.security import CurrentUser
from app.db.models import Adhesion, Comentario, HistorialEstado, Reclamo
from app.domain.enums import (
    ESTADOS_FINALES,
    CanalOrigen,
    EstadoReclamo,
    OrigenClasificacion,
    PrioridadReclamo,
    escalar,
    puede_transicionar,
)
from app.events import topics
from app.events.contracts import (
    ReclamoAdherido,
    ReclamoClasificado,
    ReclamoCreado,
    ReclamoEstadoCambiado,
    ReclamoResuelto,
)
from app.events.producer import EventPublisher
from app.repositories.reclamo_repository import FiltroReclamos, ReclamoRepository
from app.schemas.reclamo import CambioEstado, ReclamoCrear, ReclasificacionPedido
from app.services.clasificador import Clasificador, get_clasificador

log = get_logger(__name__)

USUARIO_SISTEMA = "sistema"


class ReclamoService:
    def __init__(
        self,
        session: AsyncSession,
        publisher: EventPublisher,
        clasificador: Clasificador | None = None,
        cfg: Settings | None = None,
    ) -> None:
        self.session = session
        self.repo = ReclamoRepository(session)
        self.publisher = publisher
        self.clasificador = clasificador or get_clasificador()
        self.cfg = cfg or settings

    # --- Intake --------------------------------------------------------------
    async def crear(
        self,
        datos: ReclamoCrear,
        ciudadano_id: str,
        *,
        correlation_id: str | None = None,
        evento_origen_id: str | None = None,
    ) -> Reclamo:
        """File a claim, classifying it when the citizen did not."""
        sugerencia = None
        categoria = datos.categoria
        prioridad = datos.prioridad
        origen = OrigenClasificacion.CIUDADANO
        confianza: float | None = None
        estado = EstadoReclamo.RECIBIDO

        if categoria is None or prioridad is None:
            sugerencia = self.clasificador.clasificar(datos.titulo, datos.descripcion)
            categoria = categoria or sugerencia.categoria
            prioridad = prioridad or sugerencia.prioridad
            origen = OrigenClasificacion.MODELO
            confianza = sugerencia.confianza
            # When the model is unsure, the claim goes to human triage instead
            # of landing straight in the wrong department's inbox.
            if confianza < self.cfg.confianza_minima_clasificador:
                estado = EstadoReclamo.EN_REVISION

        reclamo = Reclamo(
            ciudadano_id=ciudadano_id,
            titulo=datos.titulo,
            descripcion=datos.descripcion,
            categoria=categoria,
            prioridad=prioridad,
            estado=estado,
            origen_clasificacion=origen,
            confianza_clasificacion=confianza,
            canal=datos.canal,
            direccion=datos.direccion,
            barrio=datos.barrio,
            latitud=datos.latitud,
            longitud=datos.longitud,
            fotos=list(datos.fotos),
            correlation_id=correlation_id,
            evento_origen_id=evento_origen_id,
        )
        await self.repo.agregar(reclamo)
        await self.repo.agregar_historial(
            HistorialEstado(
                reclamo_id=reclamo.id,
                estado_anterior=None,
                estado_nuevo=estado,
                motivo="Alta del reclamo",
                usuario_id=ciudadano_id,
            )
        )
        await self.session.commit()
        await self.session.refresh(reclamo)

        await self._publicar_creado(reclamo)
        if sugerencia is not None and origen is OrigenClasificacion.MODELO:
            await self.publisher.publish(
                topics.RECLAMO_CLASIFICADO,
                ReclamoClasificado(
                    reclamo_id=reclamo.id,
                    categoria=reclamo.categoria,
                    prioridad=reclamo.prioridad,
                    confianza=sugerencia.confianza,
                    modelo=sugerencia.modelo,
                    evidencia=sugerencia.evidencia,
                ),
                key=str(reclamo.id),
                correlation_id=reclamo.correlation_id,
            )

        log.info(
            "reclamo.creado",
            reclamo_id=str(reclamo.id),
            categoria=reclamo.categoria.value,
            prioridad=reclamo.prioridad.value,
            origen=origen.value,
        )
        return reclamo

    async def _publicar_creado(self, reclamo: Reclamo) -> None:
        await self.publisher.publish(
            topics.RECLAMO_CREADO,
            ReclamoCreado(
                reclamo_id=reclamo.id,
                ciudadano_id=reclamo.ciudadano_id,
                titulo=reclamo.titulo,
                categoria=reclamo.categoria,
                prioridad=reclamo.prioridad,
                estado=reclamo.estado,
                barrio=reclamo.barrio,
                direccion=reclamo.direccion,
                latitud=reclamo.latitud,
                longitud=reclamo.longitud,
                creado_at=reclamo.created_at,
            ),
            # Keyed by claim id, which guarantees ordering per aggregate.
            key=str(reclamo.id),
            correlation_id=reclamo.correlation_id,
        )

    # --- Reads ---------------------------------------------------------------
    async def obtener(self, reclamo_id: uuid.UUID) -> Reclamo:
        reclamo = await self.repo.obtener(reclamo_id)
        if reclamo is None:
            raise ReclamoNoEncontrado(f"No existe el reclamo {reclamo_id}")
        return reclamo

    async def listar(
        self, filtro: FiltroReclamos, *, page: int = 1, size: int = 20
    ) -> tuple[list[Reclamo], int]:
        return await self.repo.listar(filtro, page=page, size=size)

    async def estadisticas(self) -> dict:
        return await self.repo.estadisticas()

    # --- Case handling -------------------------------------------------------
    async def cambiar_estado(
        self, reclamo_id: uuid.UUID, cambio: CambioEstado, actor: CurrentUser
    ) -> Reclamo:
        reclamo = await self.obtener(reclamo_id)
        anterior = reclamo.estado

        if not puede_transicionar(anterior, cambio.estado):
            raise TransicionInvalida(
                f"No se puede pasar de {anterior.value} a {cambio.estado.value}"
            )

        ahora = datetime.now(UTC)
        reclamo.estado = cambio.estado
        if cambio.asignado_a:
            reclamo.asignado_a = cambio.asignado_a
        if cambio.area_responsable:
            reclamo.area_responsable = cambio.area_responsable
        if cambio.resolucion:
            reclamo.resolucion = cambio.resolucion
        if cambio.estado is EstadoReclamo.RESUELTO:
            reclamo.resuelto_at = ahora
        if cambio.estado is EstadoReclamo.CERRADO:
            reclamo.cerrado_at = ahora

        await self.repo.agregar_historial(
            HistorialEstado(
                reclamo_id=reclamo.id,
                estado_anterior=anterior,
                estado_nuevo=cambio.estado,
                motivo=cambio.motivo,
                usuario_id=actor.id,
            )
        )
        await self.session.commit()
        await self.session.refresh(reclamo)

        await self.publisher.publish(
            topics.RECLAMO_ESTADO_CAMBIADO,
            ReclamoEstadoCambiado(
                reclamo_id=reclamo.id,
                ciudadano_id=reclamo.ciudadano_id,
                estado_anterior=anterior,
                estado_nuevo=reclamo.estado,
                motivo=cambio.motivo,
                asignado_a=reclamo.asignado_a,
                cambiado_por=actor.id,
                cambiado_at=ahora,
            ),
            key=str(reclamo.id),
            correlation_id=reclamo.correlation_id,
        )

        if reclamo.estado is EstadoReclamo.RESUELTO and reclamo.resuelto_at:
            await self.publisher.publish(
                topics.RECLAMO_RESUELTO,
                ReclamoResuelto(
                    reclamo_id=reclamo.id,
                    ciudadano_id=reclamo.ciudadano_id,
                    categoria=reclamo.categoria,
                    resolucion=reclamo.resolucion,
                    horas_hasta_resolucion=round(
                        (reclamo.resuelto_at - reclamo.created_at).total_seconds() / 3600, 2
                    ),
                    resuelto_at=reclamo.resuelto_at,
                ),
                key=str(reclamo.id),
                correlation_id=reclamo.correlation_id,
            )

        log.info(
            "reclamo.estado_cambiado",
            reclamo_id=str(reclamo.id),
            de=anterior.value,
            a=reclamo.estado.value,
            actor=actor.id,
        )
        return reclamo

    async def reclasificar(
        self, reclamo_id: uuid.UUID, cambio: ReclasificacionPedido, actor: CurrentUser
    ) -> Reclamo:
        """Let an operator correct the model's category/priority suggestion.

        Does not touch the state machine (see ADR-0005): classification already
        happens automatically on intake, this only fixes it when the model or
        the citizen got it wrong.
        """
        reclamo = await self.obtener(reclamo_id)
        if reclamo.estado in ESTADOS_FINALES:
            raise ReclamoCerrado(
                f"El reclamo esta en estado {reclamo.estado.value} y no admite reclasificacion"
            )

        if cambio.categoria is not None:
            reclamo.categoria = cambio.categoria
        if cambio.prioridad is not None:
            reclamo.prioridad = cambio.prioridad
        reclamo.origen_clasificacion = OrigenClasificacion.OPERADOR
        reclamo.confianza_clasificacion = None

        await self.session.commit()
        await self.session.refresh(reclamo)

        await self.publisher.publish(
            topics.RECLAMO_CLASIFICADO,
            ReclamoClasificado(
                reclamo_id=reclamo.id,
                categoria=reclamo.categoria,
                prioridad=reclamo.prioridad,
                confianza=1.0,
                modelo="operador",
                evidencia=[],
            ),
            key=str(reclamo.id),
            correlation_id=reclamo.correlation_id,
        )

        log.info(
            "reclamo.reclasificado",
            reclamo_id=str(reclamo.id),
            categoria=reclamo.categoria.value,
            prioridad=reclamo.prioridad.value,
            actor=actor.id,
        )
        return reclamo

    async def comentar(self, reclamo_id: uuid.UUID, texto: str, autor: CurrentUser) -> Comentario:
        reclamo = await self.obtener(reclamo_id)
        if reclamo.estado in ESTADOS_FINALES:
            raise ReclamoCerrado(
                f"El reclamo esta en estado {reclamo.estado.value} y no admite comentarios"
            )

        comentario = Comentario(
            reclamo_id=reclamo.id,
            autor_id=autor.id,
            autor_nombre=autor.nombre,
            texto=texto,
            es_oficial=autor.es_staff,
        )
        await self.repo.agregar_comentario(comentario)
        await self.session.commit()
        await self.session.refresh(comentario)
        return comentario

    # --- Citizen participation -----------------------------------------------
    async def adherir(self, reclamo_id: uuid.UUID, ciudadano_id: str) -> Reclamo:
        """Add a neighbour endorsement, escalating priority once there is consensus."""
        reclamo = await self.obtener(reclamo_id)

        if reclamo.ciudadano_id == ciudadano_id:
            raise AdhesionDelAutor()
        if reclamo.estado in ESTADOS_FINALES:
            raise ReclamoCerrado(
                f"El reclamo esta en estado {reclamo.estado.value} y no admite adhesiones"
            )
        if await self.repo.existe_adhesion(reclamo_id, ciudadano_id):
            raise AdhesionDuplicada()

        await self.repo.agregar_adhesion(Adhesion(reclamo_id=reclamo.id, ciudadano_id=ciudadano_id))
        reclamo.adhesiones_count += 1

        # Participation rule: once enough neighbours report the same problem,
        # the claim moves up in priority on its own.
        escalado = False
        if reclamo.adhesiones_count >= self.cfg.adhesiones_para_escalar:
            nueva = escalar(reclamo.prioridad, PrioridadReclamo.ALTA)
            escalado = nueva is not reclamo.prioridad
            reclamo.prioridad = nueva

        await self.session.commit()
        await self.session.refresh(reclamo)

        await self.publisher.publish(
            topics.RECLAMO_ADHERIDO,
            ReclamoAdherido(
                reclamo_id=reclamo.id,
                ciudadano_id=ciudadano_id,
                adhesiones_count=reclamo.adhesiones_count,
                prioridad=reclamo.prioridad,
                escalado=escalado,
            ),
            key=str(reclamo.id),
            correlation_id=reclamo.correlation_id,
        )
        return reclamo

    # --- Reactions to other modules' events -----------------------------------
    async def crear_desde_evento(
        self,
        datos: ReclamoCrear,
        *,
        evento_id: str,
        correlation_id: str | None = None,
        ciudadano_id: str = USUARIO_SISTEMA,
    ) -> Reclamo | None:
        """Automatic intake triggered by an external event.

        Returns `None` when the event was already processed: the UNIQUE on
        `evento_origen_id` plus this check make consumption idempotent even if
        Kafka redelivers the message.
        """
        existente = await self.repo.obtener_por_evento_origen(evento_id)
        if existente is not None:
            log.info("evento.ya_procesado", evento_id=evento_id, reclamo_id=str(existente.id))
            return None

        datos = datos.model_copy(update={"canal": CanalOrigen.EVENTO})
        return await self.crear(
            datos,
            ciudadano_id,
            correlation_id=correlation_id,
            evento_origen_id=evento_id,
        )

    async def escalar_por_incidente(
        self,
        *,
        barrio: str | None,
        motivo: str,
        prioridad_minima: PrioridadReclamo = PrioridadReclamo.ALTA,
    ) -> list[Reclamo]:
        """Raise the priority of every open claim in a given area.

        Triggered when Emergencies reports an incident: if there is a fire or a
        collapse in the neighbourhood, open claims from that area get attended
        to sooner.
        """
        if not barrio:
            return []

        abiertos = [e for e in EstadoReclamo if e not in ESTADOS_FINALES]
        candidatos, _ = await self.repo.listar(
            FiltroReclamos(barrio=barrio, estados=abiertos), page=1, size=100
        )

        afectados: list[Reclamo] = []
        for reclamo in candidatos:
            nueva = escalar(reclamo.prioridad, prioridad_minima)
            if nueva is reclamo.prioridad:
                continue
            reclamo.prioridad = nueva
            await self.repo.agregar_comentario(
                Comentario(
                    reclamo_id=reclamo.id,
                    autor_id=USUARIO_SISTEMA,
                    autor_nombre="CityPass+",
                    texto=motivo,
                    es_oficial=True,
                )
            )
            afectados.append(reclamo)

        if afectados:
            await self.session.commit()
            log.info("reclamos.escalados_por_incidente", barrio=barrio, cantidad=len(afectados))
        return afectados
