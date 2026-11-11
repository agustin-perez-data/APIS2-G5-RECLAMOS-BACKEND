"""Protected HTML proxy for the Claims dashboard hosted by Analytics."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import AdminDep, bearer_scheme
from app.core.security import OrigenIdentidad
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
    usuario: AdminDep,
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    client: Annotated[AnaliticaClient, Depends(get_analitica_client)],
) -> Response:
    # AdminDep validated this same Bearer token. Keep the raw value only for
    # the server-to-server request; CurrentUser intentionally stores no token.
    if usuario.origen is not OrigenIdentidad.IDP or (usuario.claims or {}).get("module") != (
        "reclamos"
    ):
        raise HTTPException(status_code=403, detail="Requiere admin federado de Reclamos")
    if credenciales is None or not credenciales.credentials:
        raise HTTPException(status_code=401, detail="Falta el token del usuario")

    try:
        tablero = await client.obtener_tablero(credenciales.credentials)
    except ErrorAnalitica as exc:
        codigo = 403 if exc.status_code == 403 else 502
        raise HTTPException(status_code=codigo, detail="Analítica no disponible") from exc

    headers = {
        "Content-Type": tablero.content_type,
        "Cache-Control": (
            tablero.cache_control
            if tablero.cache_control and "no-store" in tablero.cache_control.lower()
            else "no-store"
        ),
        "X-Content-Type-Options": "nosniff",
    }
    if tablero.content_security_policy:
        headers["Content-Security-Policy"] = tablero.content_security_policy
    return Response(content=tablero.html, headers=headers)
