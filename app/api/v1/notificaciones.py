"""The signed-in user's notifications inbox (ADR 0008).

The recipient always comes from the token: no endpoint takes a user id, so
nobody can read or mark someone else's notifications.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import NotificacionesDep, UsuarioDep
from app.schemas.notificacion import (
    BandejaNotificaciones,
    ConteoNotificaciones,
    LecturaMasiva,
    NotificacionOut,
)

router = APIRouter(prefix="/notificaciones", tags=["notificaciones"])


@router.get(
    "",
    response_model=BandejaNotificaciones,
    summary="Mis notificaciones",
    description=(
        "Las notificaciones del usuario autenticado, de la mas nueva a la mas vieja: "
        "cambios de estado de sus reclamos y comentarios de otros. Trae tambien "
        "`unread_count` para la campana."
    ),
)
async def listar_notificaciones(
    usuario: UsuarioDep,
    service: NotificacionesDep,
    unread_only: Annotated[bool, Query(description="Solo las no leidas")] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BandejaNotificaciones:
    items, total = await service.listar(
        usuario.id, solo_no_leidas=unread_only, page=page, size=size
    )
    return BandejaNotificaciones(
        items=[NotificacionOut.model_validate(n) for n in items],
        total=total,
        page=page,
        size=size,
        unread_count=await service.contar_no_leidas(usuario.id),
    )


@router.get(
    "/conteo",
    response_model=ConteoNotificaciones,
    summary="Cantidad de notificaciones sin leer",
    description="Consulta liviana para el polling de la campana: no trae la lista.",
)
async def contar_no_leidas(usuario: UsuarioDep, service: NotificacionesDep) -> ConteoNotificaciones:
    return ConteoNotificaciones(unread_count=await service.contar_no_leidas(usuario.id))


@router.post(
    "/leer-todas",
    response_model=LecturaMasiva,
    summary="Marcar todas mis notificaciones como leidas",
    description="Idempotente: si no queda ninguna sin leer, responde `marcadas: 0`.",
)
async def leer_todas(usuario: UsuarioDep, service: NotificacionesDep) -> LecturaMasiva:
    marcadas = await service.marcar_todas_leidas(usuario.id)
    return LecturaMasiva(marcadas=marcadas, unread_count=0)


@router.patch(
    "/{notificacion_id}/leer",
    response_model=NotificacionOut,
    summary="Marcar una notificacion como leida",
    description=(
        "Idempotente: si ya estaba leida conserva la fecha de la primera lectura. "
        "Una notificacion de otro usuario responde 404, igual que una inexistente."
    ),
)
async def leer(
    notificacion_id: uuid.UUID, usuario: UsuarioDep, service: NotificacionesDep
) -> NotificacionOut:
    notificacion = await service.marcar_leida(notificacion_id, usuario.id)
    return NotificacionOut.model_validate(notificacion)
