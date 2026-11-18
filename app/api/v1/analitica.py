"""Protected HTML proxy for the Claims dashboard hosted by Analytics."""

from __future__ import annotations

from typing import Annotated
from urllib.request import parse_http_list

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import bearer_scheme
from app.api.v1.deps_analitica import AdminAnaliticaDep
from app.integrations.analitica import AnaliticaClient, ErrorAnalitica

router = APIRouter(prefix="/admin", tags=["admin"])


def get_analitica_client(request: Request) -> AnaliticaClient:
    """The dashboard client is shared and closed by the app lifespan."""
    return request.app.state.analitica


@router.get(
    "/analitica",
    response_class=HTMLResponse,
    summary="Tablero de Analítica de Reclamos",
    description="Devuelve el tablero HTML únicamente al administrador federado de Reclamos.",
)
async def tablero_analitica(
    usuario: AdminAnaliticaDep,
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    client: Annotated[AnaliticaClient, Depends(get_analitica_client)],
) -> Response:
    # AdminAnaliticaDep validated this same Bearer token. Keep the raw value only for
    # the server-to-server request; CurrentUser intentionally stores no token.
    if credenciales is None or not credenciales.credentials:
        raise HTTPException(status_code=401, detail="Falta el token del usuario")

    try:
        tablero = await client.obtener_tablero(credenciales.credentials)
    except ErrorAnalitica as exc:
        codigo = 504 if exc.timeout else {403: 403, 503: 503}.get(exc.status_code, 502)
        raise HTTPException(
            status_code=codigo,
            detail="Analítica no disponible",
            headers={"Cache-Control": "no-store"},
        ) from exc

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
    return respuesta
