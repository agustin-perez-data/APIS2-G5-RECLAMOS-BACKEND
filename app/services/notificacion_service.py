"""In-app notifications for the owner of a claim (ADR 0008).

`ReclamoService` calls `por_cambio_de_estado` and `por_comentario` inside its
own unit of work, before the commit: the notification is saved together with
the change, or not at all. Nothing here goes through the bus, which is off in
the deploy, so the notification cannot be lost between the commit and a
publish.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotificacionNoEncontrada
from app.core.logging import get_logger
from app.db.models import Comentario, HistorialEstado, Notificacion, Reclamo
from app.domain.enums import USUARIO_SISTEMA, EstadoReclamo, TipoNotificacion
from app.repositories.notificacion_repository import NotificacionRepository

log = get_logger(__name__)

ETIQUETAS_ESTADO: dict[EstadoReclamo, str] = {
    EstadoReclamo.RECIBIDO: "Recibido",
    EstadoReclamo.EN_REVISION: "En revisión",
    EstadoReclamo.ASIGNADO: "Asignado",
    EstadoReclamo.EN_PROCESO: "En proceso",
    EstadoReclamo.RESUELTO: "Resuelto",
    EstadoReclamo.RECHAZADO: "Rechazado",
    EstadoReclamo.CERRADO: "Cerrado",
}

TITULOS_FINALES: dict[EstadoReclamo, str] = {
    EstadoReclamo.RESUELTO: "Tu reclamo fue resuelto",
    EstadoReclamo.RECHAZADO: "Tu reclamo fue rechazado",
    EstadoReclamo.CERRADO: "Tu reclamo fue cerrado",
}

LARGO_RESUMEN = 140

# Staff subs that receive fan-out notifications (new claim, citizen comment).
# Matches the dev login roster in `app/api/v1/auth_dev.py`; when Group 2's
# identity service is wired, replace this with a lookup against their roster.
STAFF_IDS: frozenset[str] = frozenset({"operador-1", "admin-1"})


def resumir(texto: str, limite: int = LARGO_RESUMEN) -> str:
    """One line, capped: a notification previews the text, it does not copy it."""
    plano = " ".join(texto.split())
    return plano if len(plano) <= limite else plano[: limite - 1].rstrip() + "…"


def titulo_cambio_estado(nuevo: EstadoReclamo) -> str:
    return TITULOS_FINALES.get(nuevo, f"Tu reclamo pasó a {ETIQUETAS_ESTADO[nuevo]}")


def mensaje_cambio_estado(
    reclamo: Reclamo, anterior: EstadoReclamo, nuevo: EstadoReclamo, motivo: str | None
) -> str:
    partes = [
        f'"{resumir(reclamo.titulo, 80)}" pasó de {ETIQUETAS_ESTADO[anterior]} '
        f"a {ETIQUETAS_ESTADO[nuevo]}."
    ]
    if motivo:
        partes.append(f"Motivo: {resumir(motivo)}")
    if nuevo is EstadoReclamo.RESUELTO and reclamo.resolucion:
        partes.append(f"Resolución: {resumir(reclamo.resolucion)}")
    return " ".join(partes)


def titulo_comentario(es_oficial: bool) -> str:
    if es_oficial:
        return "Nuevo comentario oficial en tu reclamo"
    return "Nuevo comentario en tu reclamo"


def mensaje_comentario(reclamo: Reclamo, comentario: Comentario) -> str:
    # Official replies are signed by the city, not by the operator who wrote
    # them: the operator's identity is internal.
    quien = "El municipio" if comentario.es_oficial else comentario.autor_nombre or "Otro vecino"
    return f'{quien} comentó en "{resumir(reclamo.titulo, 80)}": {resumir(comentario.texto)}'


def titulo_nuevo_reclamo() -> str:
    return "Nuevo reclamo en la bandeja"


def mensaje_nuevo_reclamo(reclamo: Reclamo) -> str:
    barrio = f" ({reclamo.barrio})" if reclamo.barrio else ""
    return (
        f'"{resumir(reclamo.titulo, 80)}"{barrio}: {ETIQUETAS_ESTADO[reclamo.estado]}, '
        f"prioridad {reclamo.prioridad.value.lower()}."
    )


def titulo_comentario_para_staff(reclamo: Reclamo) -> str:
    return f'Nuevo comentario en "{resumir(reclamo.titulo, 80)}"'


def mensaje_comentario_para_staff(reclamo: Reclamo, comentario: Comentario) -> str:
    quien = comentario.autor_nombre or "Un vecino"
    return f"{quien} comentó: {resumir(comentario.texto)}"


class NotificacionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = NotificacionRepository(session)

    # --- Creation (inside the caller's transaction) ---------------------------
    async def por_cambio_de_estado(
        self, reclamo: Reclamo, historial: HistorialEstado, *, actor_id: str
    ) -> Notificacion | None:
        if historial.estado_anterior is None:
            return None  # the filing itself: the owner knows, they just did it
        return await self._crear(
            Notificacion(
                destinatario_id=reclamo.ciudadano_id,
                reclamo_id=reclamo.id,
                tipo=TipoNotificacion.ESTADO,
                referencia_id=historial.id,
                titulo=titulo_cambio_estado(historial.estado_nuevo),
                mensaje=mensaje_cambio_estado(
                    reclamo, historial.estado_anterior, historial.estado_nuevo, historial.motivo
                ),
                datos={
                    "estado_anterior": historial.estado_anterior.value,
                    "estado_nuevo": historial.estado_nuevo.value,
                },
            ),
            actor_id=actor_id,
        )

    async def por_comentario(self, reclamo: Reclamo, comentario: Comentario) -> Notificacion | None:
        return await self._crear(
            Notificacion(
                destinatario_id=reclamo.ciudadano_id,
                reclamo_id=reclamo.id,
                tipo=TipoNotificacion.COMENTARIO,
                referencia_id=comentario.id,
                titulo=titulo_comentario(comentario.es_oficial),
                mensaje=mensaje_comentario(reclamo, comentario),
                datos={"comentario_id": str(comentario.id), "es_oficial": comentario.es_oficial},
            ),
            actor_id=comentario.autor_id,
        )

    async def por_nuevo_reclamo(self, reclamo: Reclamo) -> list[Notificacion]:
        """Fan-out to staff when a citizen files a new claim."""
        creadas: list[Notificacion] = []
        for staff_id in STAFF_IDS:
            notificacion = await self._crear(
                Notificacion(
                    destinatario_id=staff_id,
                    reclamo_id=reclamo.id,
                    tipo=TipoNotificacion.NUEVO_RECLAMO,
                    referencia_id=reclamo.id,
                    titulo=titulo_nuevo_reclamo(),
                    mensaje=mensaje_nuevo_reclamo(reclamo),
                    datos={
                        "categoria": reclamo.categoria.value,
                        "prioridad": reclamo.prioridad.value,
                        "estado": reclamo.estado.value,
                    },
                ),
                actor_id=reclamo.ciudadano_id,
            )
            if notificacion is not None:
                creadas.append(notificacion)
        return creadas

    async def por_comentario_para_staff(
        self, reclamo: Reclamo, comentario: Comentario
    ) -> list[Notificacion]:
        """Fan-out to staff when a citizen comments on a claim."""
        creadas: list[Notificacion] = []
        for staff_id in STAFF_IDS:
            notificacion = await self._crear(
                Notificacion(
                    destinatario_id=staff_id,
                    reclamo_id=reclamo.id,
                    tipo=TipoNotificacion.COMENTARIO,
                    referencia_id=comentario.id,
                    titulo=titulo_comentario_para_staff(reclamo),
                    mensaje=mensaje_comentario_para_staff(reclamo, comentario),
                    datos={
                        "comentario_id": str(comentario.id),
                        "es_oficial": comentario.es_oficial,
                    },
                ),
                actor_id=comentario.autor_id,
            )
            if notificacion is not None:
                creadas.append(notificacion)
        return creadas

    async def _crear(self, notificacion: Notificacion, *, actor_id: str) -> Notificacion | None:
        destinatario = notificacion.destinatario_id
        # Claims opened by another module's event belong to the system user,
        # and nobody reads its notifications.
        if destinatario in (USUARIO_SISTEMA, actor_id):
            return None
        # Processing the same change twice must not notify twice. The UNIQUE on
        # (destinatario_id, tipo, referencia_id) is the real guarantee; this
        # check keeps a retry from failing the whole transaction.
        if await self.repo.existe(destinatario, notificacion.tipo, notificacion.referencia_id):
            log.info(
                "notificacion.ya_existe",
                tipo=notificacion.tipo.value,
                referencia_id=str(notificacion.referencia_id),
            )
            return None
        await self.repo.agregar(notificacion)
        return notificacion

    # --- The recipient's inbox --------------------------------------------------
    async def listar(
        self, destinatario_id: str, *, solo_no_leidas: bool = False, page: int = 1, size: int = 20
    ) -> tuple[list[Notificacion], int]:
        return await self.repo.listar(
            destinatario_id, solo_no_leidas=solo_no_leidas, page=page, size=size
        )

    async def contar_no_leidas(self, destinatario_id: str) -> int:
        return await self.repo.contar_no_leidas(destinatario_id)

    async def marcar_leida(self, notificacion_id: uuid.UUID, destinatario_id: str) -> Notificacion:
        """Idempotent: reading it again keeps the first `leida_at`."""
        notificacion = await self.repo.obtener(notificacion_id)
        if notificacion is None or notificacion.destinatario_id != destinatario_id:
            raise NotificacionNoEncontrada(f"No existe la notificacion {notificacion_id}")
        if notificacion.leida_at is None:
            notificacion.leida_at = datetime.now(UTC)
            await self.session.commit()
            await self.session.refresh(notificacion)
        return notificacion

    async def marcar_todas_leidas(self, destinatario_id: str) -> int:
        marcadas = await self.repo.marcar_todas_leidas(destinatario_id, datetime.now(UTC))
        await self.session.commit()
        return marcadas
