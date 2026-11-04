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

import math
import uuid
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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
from app.db.models import Adhesion, Comentario, EventoClimatico, HistorialEstado, Reclamo
from app.domain import geo
from app.domain.barrios import barrio_afectado, normalizar_barrio
from app.domain.enums import (
    ESTADOS_FINALES,
    USUARIO_SISTEMA,
    CanalOrigen,
    CategoriaReclamo,
    EstadoEventoClimatico,
    EstadoReclamo,
    NivelCriticidad,
    OrigenClasificacion,
    PrioridadReclamo,
    ResultadoIntervencion,
    escalar,
    puede_transicionar,
)
from app.events import topics
from app.events.contracts import (
    ReclamoAdherido,
    ReclamoClasificado,
    ReclamoComentarioCreado,
    ReclamoCreado,
    ReclamoEstadoCambiado,
    ReclamoReclasificado,
    ReclamoResuelto,
)
from app.events.producer import EventPublisher
from app.integrations.tickets import SistemaTickets, TicketNuevo, get_sistema_tickets
from app.ml import similitud
from app.repositories.reclamo_repository import FiltroReclamos, ReclamoRepository
from app.schemas.reclamo import CambioEstado, ReclamoCrear, ReclasificacionPedido
from app.services.actividad_service import ActividadService
from app.services.clasificador import Clasificador, get_clasificador
from app.services.clima_service import ClimaService
from app.services.notificacion_service import NotificacionService

log = get_logger(__name__)

# What the neighbour reads when another module closes their claim. Deliberately
# generic: Public Spaces reports the outcome, not what they did, so a wording
# more specific than this would risk claiming something that never happened.
RESOLUCION_INTERVENCION: dict[ResultadoIntervencion, str] = {
    ResultadoIntervencion.RESUELTO: (
        "El area responsable intervino en la via publica y dio por resuelto el reclamo."
    ),
    ResultadoIntervencion.RECHAZADO: (
        "El area responsable reviso el reclamo y no correspondia una intervencion."
    ),
}

MOTIVO_INTERVENCION: dict[ResultadoIntervencion, str] = {
    ResultadoIntervencion.RESUELTO: "Intervencion finalizada por Espacios Publicos y Cultura",
    ResultadoIntervencion.RECHAZADO: "Espacios Publicos y Cultura no dio curso al reclamo",
}


@dataclass(frozen=True, slots=True)
class ReclamoParecido:
    """A probable duplicate, with the evidence behind the match (ADR 0007)."""

    reclamo: Reclamo
    puntaje: float
    distancia_metros: float | None
    terminos_en_comun: list[str]
    # Lets the front end offer "join it" only where it can succeed: the author
    # cannot endorse their own claim, nor anyone endorse twice.
    es_propio: bool
    ya_adherido: bool


@dataclass(frozen=True, slots=True)
class PoliticaAlerta:
    """What a severity level does to the claims it covers (ADR 0014)."""

    prioridad_minima: PrioridadReclamo
    # Categories the weather makes worse. `None` means every category.
    categorias: frozenset[CategoriaReclamo] | None
    # Endorsements needed to bump a claim under this alert, or `None` to keep
    # the global threshold.
    adhesiones: int | None


@dataclass(frozen=True, slots=True)
class ResumenAlerta:
    """Counts the summary event carries. No personal data, only numbers."""

    marcados: int
    avisos_enviados: int
    sin_ubicacion: int
    por_barrio: bool


@dataclass(frozen=True, slots=True)
class ResumenCierre:
    """Counts for the summary event published when an alert is lifted."""

    marcados: int
    abiertos_al_finalizar: int
    duplicados_detectados: int
    avisos_enviados: int
    # Claims filed while the alert was live, told apart by when they were
    # created: the ones already open when it was confirmed came before it.
    creados_durante: int
    # How many of the marked claims belong to the categories this level raises.
    # Not "how many actually moved": a claim already at CRITICA was eligible and
    # did not move, and counting it as moved would be a lie the schema's `doc`
    # would have to carry. Named for what it measures.
    subidos_de_prioridad: int
    sin_ubicacion: int


def _contar_duplicados(reclamos: Sequence[Reclamo]) -> int:
    """Claims that look like another one of the same area and category.

    Counted, not closed, and deliberately crude: same neighbourhood code and
    same category. A real duplicate check is `buscar_similares` (ADR 0007),
    which weighs text and distance; this is a number for Analytics, and dressing
    it up as more than that would invite someone to act on it.
    """
    vistos: set[tuple[str, str]] = set()
    duplicados = 0
    for reclamo in reclamos:
        if reclamo.barrio_codigo is None:
            continue
        clave = (reclamo.barrio_codigo, reclamo.categoria.value)
        if clave in vistos:
            duplicados += 1
        else:
            vistos.add(clave)
    return duplicados


def _con_zona(momento: datetime) -> datetime:
    """SQLite returns naive datetimes, PostgreSQL aware ones. Stored values are UTC."""
    return momento if momento.tzinfo is not None else momento.replace(tzinfo=UTC)


def _sensibles(cfg: Settings) -> frozenset[CategoriaReclamo]:
    return frozenset(CategoriaReclamo(c) for c in cfg.alerta_categorias_sensibles)


def _politica_de(nivel: NivelCriticidad, cfg: Settings) -> PoliticaAlerta:
    """BAJA and MEDIA only mark and tell; ALTA and CRITICA also move priority.

    MEDIA differs from BAJA in what the citizen is shown when filing, not in
    what happens to the claims already open, so both look the same here.
    """
    if nivel is NivelCriticidad.CRITICA:
        return PoliticaAlerta(
            prioridad_minima=PrioridadReclamo.CRITICA,
            categorias=_sensibles(cfg),
            adhesiones=cfg.alerta_adhesiones_critica,
        )
    if nivel is NivelCriticidad.ALTA:
        return PoliticaAlerta(
            prioridad_minima=PrioridadReclamo.ALTA,
            categorias=_sensibles(cfg),
            adhesiones=cfg.alerta_adhesiones_alta,
        )
    # BAJA and MEDIA: the claim is marked and the neighbour told, nothing else.
    # `categorias=frozenset()` means no category qualifies for a bump.
    return PoliticaAlerta(
        prioridad_minima=PrioridadReclamo.BAJA, categorias=frozenset(), adhesiones=None
    )


def _radio_metros(nivel: NivelCriticidad, cfg: Settings) -> float:
    radios = {
        NivelCriticidad.BAJA: cfg.alerta_radio_km_baja,
        NivelCriticidad.MEDIA: cfg.alerta_radio_km_media,
        NivelCriticidad.ALTA: cfg.alerta_radio_km_alta,
    }
    return radios.get(nivel, cfg.alerta_radio_km_alta) * 1000


class ReclamoService:
    def __init__(
        self,
        session: AsyncSession,
        publisher: EventPublisher,
        clasificador: Clasificador | None = None,
        cfg: Settings | None = None,
        tickets: SistemaTickets | None = None,
    ) -> None:
        self.session = session
        self.repo = ReclamoRepository(session)
        self.publisher = publisher
        self.clasificador = clasificador or get_clasificador()
        self.cfg = cfg or settings
        self.tickets = tickets or get_sistema_tickets()
        self.notificaciones = NotificacionService(session)
        self.actividades = ActividadService(session, self.cfg)
        self.clima = ClimaService(session)

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

        # Squad 3 (ADR 0013): a claim filed near a mass activity while it lasts
        # is related to it. Without coordinates there is no way to tell.
        actividad = None
        if datos.latitud is not None and datos.longitud is not None:
            actividad = await self.actividades.en_curso_cerca(datos.latitud, datos.longitud)

        reclamo = Reclamo(
            ciudadano_id=ciudadano_id,
            titulo=datos.titulo,
            descripcion=datos.descripcion,
            categoria=categoria,
            prioridad=prioridad,
            estado=estado,
            objeto_afectado=datos.objeto_afectado,
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
            actividad=actividad,
        )
        await self.repo.agregar(reclamo)
        # Stage 2: a claim filed while an alert is live joins it and, if its
        # category is one the weather makes worse, is raised on the spot.
        await self.marcar_bajo_alerta(reclamo)
        await self.repo.agregar_historial(
            HistorialEstado(
                reclamo_id=reclamo.id,
                estado_anterior=None,
                estado_nuevo=estado,
                motivo="Alta del reclamo",
                usuario_id=ciudadano_id,
            )
        )
        # Also for claims opened by another module's event: a saturated container
        # is precisely the one the staff needs to see. `_crear` already skips the
        # system user and the actor, so nobody notifies themselves.
        await self.notificaciones.por_nuevo_reclamo(reclamo)
        await self.session.commit()
        await self.session.refresh(reclamo)

        await self._publicar_creado(reclamo)
        if sugerencia is not None and origen is OrigenClasificacion.MODELO:
            await self.publisher.publish(
                topics.RECLAMO_CLASIFICADO,
                ReclamoClasificado(
                    reclamo_id=reclamo.id,
                    categoria=reclamo.categoria,
                    objeto_afectado=reclamo.objeto_afectado,
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
        if actividad is not None:
            log.info(
                "reclamo.relacionado_con_actividad",
                reclamo_id=str(reclamo.id),
                actividad_id=str(actividad.id),
            )
        await self._abrir_ticket(reclamo)
        return reclamo

    async def _abrir_ticket(self, reclamo: Reclamo) -> None:
        """Open the claim's ticket in the issue tracker.

        Runs after the commit, like event publication: a tracker outage must
        never undo or block the filing of a claim. When it fails the claim keeps
        `ticket_externo` empty, which is what makes it findable to retry.
        """
        try:
            clave = await self.tickets.crear(
                TicketNuevo(
                    reclamo_id=reclamo.id,
                    titulo=reclamo.titulo,
                    descripcion=reclamo.descripcion,
                    categoria=reclamo.categoria,
                    prioridad=reclamo.prioridad,
                    canal=reclamo.canal,
                    direccion=reclamo.direccion,
                    barrio=reclamo.barrio,
                    creado_at=reclamo.created_at,
                )
            )
        except Exception as exc:  # noqa: BLE001 - the claim is already filed
            log.warning("reclamo.ticket_fallido", reclamo_id=str(reclamo.id), error=str(exc))
            return

        if clave is None:
            return
        reclamo.ticket_externo = clave
        await self.session.commit()
        log.info("reclamo.ticket_abierto", reclamo_id=str(reclamo.id), ticket=clave)

    async def _publicar_creado(self, reclamo: Reclamo) -> None:
        await self.publisher.publish(
            topics.RECLAMO_CREADO,
            ReclamoCreado(
                reclamo_id=reclamo.id,
                ciudadano_id=reclamo.ciudadano_id,
                titulo=reclamo.titulo,
                categoria=reclamo.categoria,
                objeto_afectado=reclamo.objeto_afectado,
                prioridad=reclamo.prioridad,
                estado=reclamo.estado,
                barrio=reclamo.barrio,
                direccion=reclamo.direccion,
                latitud=reclamo.latitud,
                longitud=reclamo.longitud,
                creado_at=reclamo.created_at,
                canal=reclamo.canal,
                descripcion=reclamo.descripcion,
                origen_clasificacion=reclamo.origen_clasificacion,
                confianza_clasificacion=reclamo.confianza_clasificacion,
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

        return await self._aplicar_cambio_estado(reclamo, cambio, actor.id)

    async def _aplicar_cambio_estado(
        self, reclamo: Reclamo, cambio: CambioEstado, actor_id: str
    ) -> Reclamo:
        """Write the change, its history, its notification and its events.

        Split out of `cambiar_estado` because the state machine check is not the
        only way in: when another module finishes the job in the street the
        claim lands on its final state without walking our internal workflow
        (see `finalizar_por_intervencion` and ADR 0012).
        """
        anterior = reclamo.estado

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

        historial = await self.repo.agregar_historial(
            HistorialEstado(
                reclamo_id=reclamo.id,
                estado_anterior=anterior,
                estado_nuevo=cambio.estado,
                motivo=cambio.motivo,
                usuario_id=actor_id,
            )
        )
        # Same transaction as the change: saved together with it or not at all.
        await self.notificaciones.por_cambio_de_estado(reclamo, historial, actor_id=actor_id)
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
                cambiado_por=actor_id,
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
                    objeto_afectado=reclamo.objeto_afectado,
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
            actor=actor_id,
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

        categoria_anterior = reclamo.categoria
        prioridad_anterior = reclamo.prioridad
        objeto_anterior = reclamo.objeto_afectado

        if cambio.categoria is not None:
            reclamo.categoria = cambio.categoria
        if cambio.prioridad is not None:
            reclamo.prioridad = cambio.prioridad
        if cambio.objeto_afectado is not None:
            reclamo.objeto_afectado = cambio.objeto_afectado
        reclamo.origen_clasificacion = OrigenClasificacion.OPERADOR
        reclamo.confianza_clasificacion = None

        await self.session.commit()
        await self.session.refresh(reclamo)

        # Not ReclamoClasificado: that one describes what the model decided and
        # would force us to fill its confidence, name and evidence with made-up
        # values. Consumers also need the previous classification to undo what
        # they did with the old one.
        await self.publisher.publish(
            topics.RECLAMO_RECLASIFICADO,
            ReclamoReclasificado(
                reclamo_id=reclamo.id,
                ciudadano_id=reclamo.ciudadano_id,
                categoria_anterior=categoria_anterior,
                categoria_nueva=reclamo.categoria,
                prioridad_anterior=prioridad_anterior,
                prioridad_nueva=reclamo.prioridad,
                objeto_afectado_anterior=objeto_anterior,
                objeto_afectado_nuevo=reclamo.objeto_afectado,
                titulo=reclamo.titulo,
                descripcion=reclamo.descripcion,
                barrio=reclamo.barrio,
                latitud=reclamo.latitud,
                longitud=reclamo.longitud,
                reclasificado_por=actor.id,
                reclasificado_at=reclamo.updated_at,
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
        await self.notificaciones.por_comentario(reclamo, comentario)
        if not autor.es_staff:
            await self.notificaciones.por_comentario_para_staff(reclamo, comentario)
        await self.session.commit()
        await self.session.refresh(comentario)

        await self._publicar_comentario(reclamo, comentario)
        return comentario

    async def _publicar_comentario(self, reclamo: Reclamo, comentario: Comentario) -> None:
        await self.publisher.publish(
            topics.RECLAMO_COMENTARIO_CREADO,
            ReclamoComentarioCreado(
                comentario_id=comentario.id,
                reclamo_id=reclamo.id,
                ciudadano_id=reclamo.ciudadano_id,
                autor_id=comentario.autor_id,
                autor_nombre=comentario.autor_nombre,
                es_oficial=comentario.es_oficial,
                created_at=comentario.created_at,
            ),
            key=str(reclamo.id),
            correlation_id=reclamo.correlation_id,
        )

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
        # the claim moves up in priority on its own. Under an active weather
        # alert the bar is lower, because the same problem gets reported by many
        # neighbours at once and waiting for ten is waiting too long.
        umbral = await self._umbral_de_adhesiones(reclamo)
        escalado = False
        if reclamo.adhesiones_count >= umbral:
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

    # --- Similar claims (ADR 0007) ---------------------------------------------
    async def buscar_similares(
        self,
        *,
        titulo: str,
        descripcion: str,
        categoria: CategoriaReclamo | None = None,
        latitud: float | None = None,
        longitud: float | None = None,
        barrio: str | None = None,
        ciudadano_id: str | None = None,
        excluir_id: uuid.UUID | None = None,
    ) -> list[ReclamoParecido]:
        """Claims that are probably about the same problem, best match first.

        Before filing, the citizen gets the chance to join an existing claim
        instead of opening a duplicate; on a filed claim, the operator sees its
        duplicates without reading the whole inbox. Nothing is persisted: the
        grouping happens through endorsements, which already exist.
        """
        cfg = self.cfg
        if categoria is None:
            categoria = self.clasificador.clasificar(titulo, descripcion).categoria

        con_coordenadas = latitud is not None and longitud is not None
        caja = (
            geo.caja_alrededor(latitud, longitud, cfg.similares_radio_metros)
            if con_coordenadas
            else None
        )
        candidatos = await self.repo.candidatos_similares(
            categoria=categoria,
            desde=datetime.now(UTC) - timedelta(days=cfg.similares_ventana_dias),
            caja=caja,
            barrio=barrio,
            excluir_id=excluir_id,
        )
        if not candidatos:
            return []

        consulta = f"{titulo} {descripcion}"
        textos = [f"{c.titulo} {c.descripcion}" for c in candidatos]
        puntajes_texto = similitud.similitudes(
            similitud.tokens(consulta), [similitud.tokens(t) for t in textos]
        )

        elegidos: list[tuple[Reclamo, float, float | None, str]] = []
        for candidato, texto, puntaje_texto in zip(candidatos, textos, puntajes_texto, strict=True):
            distancia = None
            if con_coordenadas and candidato.latitud is not None and candidato.longitud is not None:
                distancia = geo.distancia_metros(
                    latitud, longitud, candidato.latitud, candidato.longitud
                )
                if distancia > cfg.similares_radio_metros:
                    continue  # inside the bounding box, outside the circle
            puntaje = self._puntaje_similitud(puntaje_texto, distancia)
            if puntaje >= cfg.similares_puntaje_minimo:
                elegidos.append((candidato, puntaje, distancia, texto))

        # Best match first; on a tie, the closest one.
        elegidos.sort(key=lambda e: (-e[1], e[2] if e[2] is not None else math.inf))
        elegidos = elegidos[: cfg.similares_maximo]

        adheridos = (
            await self.repo.adheridos_por(ciudadano_id, [e[0].id for e in elegidos])
            if ciudadano_id
            else set()
        )
        return [
            ReclamoParecido(
                reclamo=candidato,
                puntaje=round(puntaje, 3),
                distancia_metros=round(distancia) if distancia is not None else None,
                terminos_en_comun=similitud.terminos_en_comun(consulta, texto),
                es_propio=ciudadano_id is not None and candidato.ciudadano_id == ciudadano_id,
                ya_adherido=candidato.id in adheridos,
            )
            for candidato, puntaje, distancia, texto in elegidos
        ]

    async def similares_de(
        self, reclamo_id: uuid.UUID, *, ciudadano_id: str | None = None
    ) -> list[ReclamoParecido]:
        """Probable duplicates of a filed claim, for the operator's review."""
        reclamo = await self.obtener(reclamo_id)
        return await self.buscar_similares(
            titulo=reclamo.titulo,
            descripcion=reclamo.descripcion,
            categoria=reclamo.categoria,
            latitud=reclamo.latitud,
            longitud=reclamo.longitud,
            barrio=reclamo.barrio,
            ciudadano_id=ciudadano_id,
            excluir_id=reclamo.id,
        )

    def _puntaje_similitud(self, texto: float, distancia: float | None) -> float:
        """Blend text and proximity. Without a distance, the text is all there is."""
        if distancia is None:
            return texto
        peso = self.cfg.similares_peso_texto
        cercania = 1 - distancia / self.cfg.similares_radio_metros
        return peso * texto + (1 - peso) * cercania

    # --- Reactions to other modules' events -----------------------------------
    async def finalizar_por_intervencion(
        self, reclamo_id: uuid.UUID, resultado: ResultadoIntervencion
    ) -> Reclamo | None:
        """Close a claim that another module resolved out in the street (CU-INT-01).

        Public Spaces does the work, so the claim never walked our own
        ASIGNADO and EN_PROCESO. Forcing it through them to satisfy the state
        machine would be inventing a history that did not happen: nobody here
        was assigned to it and nobody here worked it. It lands on its final
        state in one step, and the history entry says the change came from
        outside.

        Returns None when there is nothing to do, which is what makes a
        redelivery harmless: the gateway is at-least-once.
        """
        reclamo = await self.repo.obtener(reclamo_id)
        if reclamo is None:
            # A claim of another module, or one that no longer exists. Ignoring
            # it beats a 500 that makes the gateway retry forever.
            log.warning("handler.intervencion.reclamo_inexistente", reclamo_id=str(reclamo_id))
            return None

        destino = (
            EstadoReclamo.RESUELTO
            if resultado is ResultadoIntervencion.RESUELTO
            else EstadoReclamo.RECHAZADO
        )
        if reclamo.estado is destino or reclamo.estado in ESTADOS_FINALES:
            log.info(
                "handler.intervencion.sin_cambios",
                reclamo_id=str(reclamo.id),
                estado=reclamo.estado.value,
            )
            return None

        cambio = CambioEstado(
            estado=destino,
            motivo=MOTIVO_INTERVENCION[resultado],
            resolucion=RESOLUCION_INTERVENCION[resultado],
        )
        return await self._aplicar_cambio_estado(reclamo, cambio, USUARIO_SISTEMA)

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

        afectados = await self._aplicar_escalada(
            candidatos, motivo=motivo, prioridad_minima=prioridad_minima
        )
        if not afectados:
            return []

        await self._confirmar_escalada(afectados)
        log.info("reclamos.escalados_por_incidente", barrio=barrio, cantidad=len(afectados))
        return [reclamo for reclamo, _ in afectados]

    async def _aplicar_escalada(
        self,
        candidatos: Sequence[Reclamo],
        *,
        motivo: str,
        prioridad_minima: PrioridadReclamo,
        alerta_id: uuid.UUID | None = None,
        solo_categorias: Collection[CategoriaReclamo] | None = None,
        avisar_siempre: bool = False,
    ) -> list[tuple[Reclamo, Comentario]]:
        """Raise priority, leave an official comment and notify. Shared body.

        Used by the Emergencies incident and by the weather alert: both do the
        same thing to a set of claims and differ only in how that set is chosen.
        Nothing is committed here -- see `_confirmar_escalada`.

        `solo_categorias` limits the priority bump to the categories the weather
        makes worse. Claims outside it still get marked with the alert and still
        get told, because the neighbour deserves to know either way.

        `avisar_siempre` is for the message that carries no priority change at
        all -- the alert being lifted. Without it nobody would be told it ended,
        because no priority moves and every claim would be skipped.
        """
        afectados: list[tuple[Reclamo, Comentario]] = []
        for reclamo in candidatos:
            if alerta_id is not None:
                reclamo.alerta_id = alerta_id

            sube = solo_categorias is None or reclamo.categoria in solo_categorias
            nueva = escalar(reclamo.prioridad, prioridad_minima) if sube else reclamo.prioridad
            # A claim already at or above the floor keeps its priority, but when
            # it belongs to an alert, or the message is the point, it is still
            # marked and still notified.
            if nueva is reclamo.prioridad and alerta_id is None and not avisar_siempre:
                continue
            reclamo.prioridad = nueva

            comentario = await self.repo.agregar_comentario(
                Comentario(
                    reclamo_id=reclamo.id,
                    autor_id=USUARIO_SISTEMA,
                    autor_nombre="CityPass+",
                    texto=motivo,
                    es_oficial=True,
                )
            )
            await self.notificaciones.por_comentario(reclamo, comentario)
            afectados.append((reclamo, comentario))
        return afectados

    async def alerta_que_cubre(self, reclamo: Reclamo) -> EventoClimatico | None:
        """The live alert this claim falls under, if any.

        Evaluated when the claim is filed rather than by a scheduler: there is
        no job flipping alerts to active, so "is it in force right now" is
        answered at the only moment it matters.

        An alert that was confirmed but whose window has not opened yet does not
        count: Public Spaces can announce a storm for tonight, and a claim filed
        this morning is not under it.
        """
        ahora = datetime.now(UTC)
        for alerta in await self.clima.repo.activas():
            if _con_zona(alerta.vigencia_desde) > ahora:
                continue
            if alerta.barrios:
                if barrio_afectado(reclamo.barrio, alerta.barrios):
                    return alerta
                continue
            if reclamo.latitud is None or reclamo.longitud is None:
                continue
            radio = _radio_metros(alerta.nivel, self.cfg)
            for punto in alerta.ubicaciones:
                lat, lon = punto.get("latitud"), punto.get("longitud")
                if lat is None or lon is None:
                    continue
                if geo.distancia_metros(lat, lon, reclamo.latitud, reclamo.longitud) <= radio:
                    return alerta
        return None

    async def marcar_bajo_alerta(self, reclamo: Reclamo) -> EventoClimatico | None:
        """Stage 2: a claim filed while an alert is live joins it.

        Returns the alert so the caller can tell the citizen in the very
        response to the filing, instead of only in a later notification.
        """
        alerta = await self.alerta_que_cubre(reclamo)
        if alerta is None:
            return None

        reclamo.alerta_id = alerta.alerta_id
        politica = _politica_de(alerta.nivel, self.cfg)
        if politica.categorias and reclamo.categoria in politica.categorias:
            reclamo.prioridad = escalar(reclamo.prioridad, politica.prioridad_minima)
        return alerta

    async def _umbral_de_adhesiones(self, reclamo: Reclamo) -> int:
        """Endorsements this claim needs to escalate, right now.

        The reduced threshold applies **only to a claim marked with an alert
        that is still live**, never to the global setting: lowering the global
        one would change the rule for the whole city, including the
        neighbourhoods where nothing is happening.

        A claim keeps its `alerta_id` after the alert ends -- it is history, and
        Analytics reads it -- so the alert's state is what decides, not the mark.
        """
        if reclamo.alerta_id is None:
            return self.cfg.adhesiones_para_escalar

        alerta = await self.clima.repo.obtener(reclamo.alerta_id)
        if alerta is None or alerta.estado is EstadoEventoClimatico.FINALIZADA:
            return self.cfg.adhesiones_para_escalar

        politica = _politica_de(alerta.nivel, self.cfg)
        return politica.adhesiones or self.cfg.adhesiones_para_escalar

    # --- Weather alert (ADR 0014) --------------------------------------------
    AVISO_ALERTA = (
        "Tu reclamo sigue registrado. Por la alerta climatica en tu zona la "
        "gestion puede demorarse. Te avisamos cuando termine."
    )
    AVISO_FIN_ALERTA = "Termino la alerta climatica en tu zona. Retomamos la gestion de tu reclamo."

    async def escalar_por_alerta_climatica(self, alerta: EventoClimatico) -> ResumenAlerta:
        """Mark the open claims in the alert's area and raise their priority.

        The area is primary by neighbourhood: Public Spaces works out which ones
        are affected and sends them. Only when that list is empty does this fall
        back to a radius around the points they consulted, and that radius is a
        convention of ours -- the alert gives points, not an area.

        Reads in batches: an alert can cover the whole city, and stopping at a
        page would leave claims out without anyone noticing.
        """
        politica = _politica_de(alerta.nivel, self.cfg)
        marcados: list[Reclamo] = []
        desplazamiento = 0

        while True:
            lote = await self._candidatos_de_alerta(alerta, desplazamiento=desplazamiento)
            if not lote:
                break
            afectados = await self._aplicar_escalada(
                lote,
                motivo=self.AVISO_ALERTA,
                prioridad_minima=politica.prioridad_minima,
                alerta_id=alerta.alerta_id,
                solo_categorias=politica.categorias,
            )
            if afectados:
                await self._confirmar_escalada(afectados)
                marcados.extend(reclamo for reclamo, _ in afectados)
            desplazamiento += self.cfg.alerta_lote_reclamos

        sin_ubicacion = await self.repo.contar_sin_ubicacion()
        log.info(
            "reclamos.escalados_por_alerta",
            alerta_id=str(alerta.alerta_id),
            nivel=alerta.nivel.value,
            marcados=len(marcados),
            sin_ubicacion=sin_ubicacion,
            por_barrio=bool(alerta.barrios),
        )
        return ResumenAlerta(
            marcados=len(marcados),
            avisos_enviados=len(marcados),
            sin_ubicacion=sin_ubicacion,
            por_barrio=bool(alerta.barrios),
        )

    async def cerrar_alerta_climatica(self, alerta: EventoClimatico) -> ResumenCierre:
        """Stage 3: the alert ended. Tell the neighbours and count what happened.

        Duplicates are **detected and counted, never closed**: closing a
        neighbour's claim because it looks like another one, with nobody
        looking, is not a call this module gets to make.

        The `alerta_id` stays on the claims. It is history, and it is what lets
        Analytics tell the claims an alert moved from the rest.
        """
        marcados = await self.repo.marcados_con_alerta(alerta.alerta_id)
        abiertos = [r for r in marcados if r.estado not in ESTADOS_FINALES]

        afectados = await self._aplicar_escalada(
            abiertos,
            motivo=self.AVISO_FIN_ALERTA,
            prioridad_minima=PrioridadReclamo.BAJA,
            avisar_siempre=True,
        )
        if afectados:
            await self._confirmar_escalada(afectados)

        duplicados = _contar_duplicados(abiertos)
        politica = _politica_de(alerta.nivel, self.cfg)
        sensibles = politica.categorias or frozenset()
        desde = _con_zona(alerta.vigencia_desde)
        creados_durante = sum(1 for r in marcados if _con_zona(r.created_at) >= desde)
        elegibles = sum(1 for r in marcados if r.categoria in sensibles)
        sin_ubicacion = await self.repo.contar_sin_ubicacion()
        log.info(
            "reclamos.alerta_levantada",
            alerta_id=str(alerta.alerta_id),
            marcados=len(marcados),
            abiertos=len(abiertos),
            duplicados=duplicados,
        )
        return ResumenCierre(
            marcados=len(marcados),
            abiertos_al_finalizar=len(abiertos),
            duplicados_detectados=duplicados,
            avisos_enviados=len(afectados),
            creados_durante=creados_durante,
            subidos_de_prioridad=elegibles,
            sin_ubicacion=sin_ubicacion,
        )

    async def _candidatos_de_alerta(
        self, alerta: EventoClimatico, *, desplazamiento: int
    ) -> list[Reclamo]:
        """One batch of the claims the alert covers."""
        lote = self.cfg.alerta_lote_reclamos

        if alerta.barrios:
            # Normalised again on read, even though ClimaService already stores
            # them as codes. It costs nothing on a short list and removes a
            # tacit assumption: an alert stored by any other path would fail
            # this cross silently, with no error and no claim marked.
            codigos = [c for b in alerta.barrios if (c := normalizar_barrio(b))]
            return await self.repo.abiertos_en_barrios(
                codigos, limite=lote, desplazamiento=desplazamiento
            )

        # No neighbourhoods: fall back to geography.
        if alerta.nivel is NivelCriticidad.CRITICA:
            return await self.repo.abiertos_con_ubicacion(
                limite=lote, desplazamiento=desplazamiento
            )

        radio_metros = _radio_metros(alerta.nivel, self.cfg)
        dentro: list[Reclamo] = []
        for punto in alerta.ubicaciones:
            lat, lon = punto.get("latitud"), punto.get("longitud")
            if lat is None or lon is None:
                continue
            caja = geo.caja_alrededor(lat, lon, radio_metros)
            candidatos = await self.repo.abiertos_en_caja(
                caja, limite=lote, desplazamiento=desplazamiento
            )
            # The box contains the circle but is larger: measure the real
            # distance so a claim in the corner does not sneak in.
            dentro.extend(
                reclamo
                for reclamo in candidatos
                if reclamo.latitud is not None
                and reclamo.longitud is not None
                and geo.distancia_metros(lat, lon, reclamo.latitud, reclamo.longitud)
                <= radio_metros
            )

        vistos: set[uuid.UUID] = set()
        unicos: list[Reclamo] = []
        for reclamo in dentro:
            if reclamo.id not in vistos:
                vistos.add(reclamo.id)
                unicos.append(reclamo)
        return unicos

    async def _confirmar_escalada(self, afectados: list[tuple[Reclamo, Comentario]]) -> None:
        """Commit once, then publish. Events go out after the commit (ADR 0004)."""
        await self.session.commit()
        for reclamo, comentario in afectados:
            await self._publicar_comentario(reclamo, comentario)

    async def cerrar_resueltos_vencidos(self) -> list[Reclamo]:
        """Auto-close claims sitting in RESUELTO past the response window (US-17).

        Runs periodically from the worker (see `app/worker.py`); a citizen who
        never responds is not expected to keep a claim open forever.
        """
        limite = datetime.now(UTC) - timedelta(days=self.cfg.dias_cierre_automatico)
        candidatos = await self.repo.resueltos_antes_de(limite)

        cerrados: list[Reclamo] = []
        for reclamo in candidatos:
            reclamo.estado = EstadoReclamo.CERRADO
            reclamo.cerrado_at = datetime.now(UTC)
            historial = await self.repo.agregar_historial(
                HistorialEstado(
                    reclamo_id=reclamo.id,
                    estado_anterior=EstadoReclamo.RESUELTO,
                    estado_nuevo=EstadoReclamo.CERRADO,
                    motivo=(
                        f"Cierre automatico: sin respuesta a los "
                        f"{self.cfg.dias_cierre_automatico} dias de resuelto"
                    ),
                    usuario_id=USUARIO_SISTEMA,
                )
            )
            await self.notificaciones.por_cambio_de_estado(
                reclamo, historial, actor_id=USUARIO_SISTEMA
            )
            cerrados.append(reclamo)

        if not cerrados:
            return []

        await self.session.commit()
        for reclamo in cerrados:
            await self.session.refresh(reclamo)
            await self.publisher.publish(
                topics.RECLAMO_ESTADO_CAMBIADO,
                ReclamoEstadoCambiado(
                    reclamo_id=reclamo.id,
                    ciudadano_id=reclamo.ciudadano_id,
                    estado_anterior=EstadoReclamo.RESUELTO,
                    estado_nuevo=EstadoReclamo.CERRADO,
                    motivo="Cierre automatico por falta de respuesta",
                    asignado_a=reclamo.asignado_a,
                    cambiado_por=USUARIO_SISTEMA,
                    cambiado_at=reclamo.cerrado_at,
                ),
                key=str(reclamo.id),
                correlation_id=reclamo.correlation_id,
            )

        log.info("reclamos.cierre_automatico", cantidad=len(cerrados))
        return cerrados
