"""Protected HTML proxy for the Claims dashboard hosted by Analytics."""

from __future__ import annotations

import hmac
import math
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated
from urllib.request import parse_http_list

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.analitica_sesion import (
    COOKIE,
    RUTA,
    RutaAnalitica,
    borrar_cookie,
    cookie_id,
    csrf,
    navegacion_valida,
    origen_valido,
)
from app.core.analitica_auth import autenticar_admin_analitica
from app.core.config import settings
from app.core.exceptions import AnaliticaAccesoDenegado, SesionAnaliticaInvalida
from app.core.security import TokenInvalido
from app.db.session import get_session
from app.integrations.analitica import AnaliticaClient, ErrorAnalitica
from app.schemas.analitica import EstadoSesionAnalitica, InicioSesionAnalitica
from app.services.sesion_analitica_service import SesionAnaliticaService

router = APIRouter(prefix="/admin", tags=["admin"], route_class=RutaAnalitica)
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _token(request: Request) -> str:
    if len(request.headers.getlist("authorization")) != 1:
        raise TokenInvalido("Authorization ambiguo o ausente")
    esquema, _, token = request.headers.get("authorization", "").partition(" ")
    if esquema.lower() != "bearer" or not token:
        raise TokenInvalido("Falta Bearer humano")
    autenticar_admin_analitica(token)
    return token


def _servicio(session: AsyncSession) -> SesionAnaliticaService:
    if settings.analitica_session_key is None:
        raise HTTPException(503, "Sesiones de Analítica no configuradas")
    try:
        return SesionAnaliticaService(session, settings)
    except ValueError as exc:
        raise HTTPException(503, "Sesiones de Analítica no configuradas") from exc


@router.post(
    "/analitica/sesion",
    response_model=InicioSesionAnalitica,
    summary="Inicializar sesión del iframe de Analítica",
)
async def iniciar_sesion(
    request: Request, response: Response, session: SessionDep
) -> InicioSesionAnalitica:
    origen_valido(request, settings)
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(415, "Requiere application/json")
    servicio = _servicio(session)
    anterior = cookie_id(request)
    try:
        token = _token(request)
    except (TokenInvalido, AnaliticaAccesoDenegado):
        if anterior:
            with suppress(SesionAnaliticaInvalida):
                await servicio.revocar(anterior)
        request.state.analitica_borrar_cookie = True
        raise
    # Expired/revoked cookies can be discarded; a live cookie is rotated atomically.
    if anterior:
        try:
            await servicio.obtener(anterior)
        except (SesionAnaliticaInvalida, TokenInvalido, AnaliticaAccesoDenegado):
            with suppress(SesionAnaliticaInvalida):
                await servicio.revocar(anterior)
            anterior = None
    creada = await servicio.crear(token, anterior=anterior)
    response.set_cookie(
        COOKIE,
        creada.identificador,
        path=RUTA,
        secure=True,
        httponly=True,
        samesite="Strict",
        max_age=max(0, min(300, math.floor((creada.vence_at - datetime.now(UTC)).total_seconds()))),
    )
    return InicioSesionAnalitica(
        usuario_id=creada.usuario_id,
        expires_at=creada.vence_at,
        iframe_url=RUTA,
        csrf_token=csrf(creada.identificador, settings),
    )


@router.get(
    "/analitica/sesion",
    response_model=EstadoSesionAnalitica,
    summary="Consultar sesión de Analítica",
)
async def estado_sesion(request: Request, session: SessionDep) -> EstadoSesionAnalitica:
    token = _token(request)
    usuario = autenticar_admin_analitica(token)
    identificador = cookie_id(request)
    if not identificador:
        raise SesionAnaliticaInvalida()
    vigente = await _servicio(session).obtener(identificador, usuario_id=usuario.id)
    return EstadoSesionAnalitica(usuario_id=usuario.id, expires_at=vigente.vence_at)


@router.delete("/analitica/sesion", summary="Revocar sesión de Analítica")
async def terminar_sesion(request: Request, response: Response, session: SessionDep) -> dict:
    origen_valido(request, settings)
    identificador = cookie_id(request)
    if identificador:
        if not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode(), csrf(identificador, settings).encode()
        ):
            raise HTTPException(403, "CSRF inválido")
        await _servicio(session).revocar(identificador)
    borrar_cookie(response)
    return {"revocada": True}


def get_analitica_client(request: Request) -> AnaliticaClient:
    """The dashboard client is shared and closed by the app lifespan."""
    return request.app.state.analitica


# Also with a trailing slash. The frontend's reverse proxy rewrites
# `/api/v1/admin/analitica` to `.../analitica/`, and the default answer to that
# is a 307 to this service's own host. The iframe followed it and left the
# frontend's origin, where its SameSite=Strict cookie is not sent and the
# navigation is no longer same-origin: the dashboard never loaded.
@router.get("/analitica/", response_class=HTMLResponse, include_in_schema=False)
@router.get(
    "/analitica",
    response_class=HTMLResponse,
    summary="Tablero de Analítica de Reclamos",
    description="Devuelve el tablero HTML únicamente al administrador federado de Reclamos.",
)
async def tablero_analitica(
    request: Request,
    session: SessionDep,
    client: Annotated[AnaliticaClient, Depends(get_analitica_client)],
) -> Response:
    identificador = None
    if "authorization" in request.headers:
        token = _token(request)
    else:
        identificador = cookie_id(request)
        if not identificador:
            raise TokenInvalido("Falta credencial")
        navegacion_valida(request)
        token = (await _servicio(session).obtener(identificador)).token_humano

    try:
        tablero = await client.obtener_tablero(token)
    except ErrorAnalitica as exc:
        codigo = 504 if exc.timeout else {403: 403, 503: 503}.get(exc.status_code, 502)
        raise HTTPException(
            status_code=codigo,
            detail="Analítica no disponible",
            headers={"Cache-Control": "no-store"},
        ) from exc

    if identificador:
        await _servicio(session).obtener(identificador)
    respuesta = Response(content=tablero.html)
    respuesta.raw_headers.extend(tablero.headers)
    # Keep upstream fields intact and enforce our own non-storage requirement.
    directivas = {
        parte.strip().lower()
        for valor in respuesta.headers.getlist("cache-control")
        for parte in parse_http_list(valor)
    }
    if "no-store" not in directivas:
        respuesta.headers.append("Cache-Control", "no-store")
    respuesta.headers.append("Content-Security-Policy", "sandbox allow-scripts")
    return respuesta
