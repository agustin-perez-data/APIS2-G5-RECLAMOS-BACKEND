"""Scoped cookie, origin and CSRF controls for the Analytics routes."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from urllib.request import parse_http_list

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.core.config import Settings
from app.core.exceptions import DomainError
from app.core.security import TokenInvalido

COOKIE = "__Secure-citypass_analitica"
RUTA = "/api/v1/admin/analitica"


def cookie_id(request: Request) -> str | None:
    # Reject ambiguous duplicate cookies instead of trusting parser ordering.
    nombres = [p.split("=", 1)[0].strip() for p in request.headers.get("cookie", "").split(";")]
    if nombres.count(COOKIE) > 1:
        raise HTTPException(400, "Cookie de Analítica ambigua")
    return request.cookies.get(COOKIE)


def origen_valido(request: Request, cfg: Settings) -> None:
    origen = request.headers.get("origin")
    if (
        len(request.headers.getlist("origin")) != 1
        or not origen
        or origen == "null"
        or origen not in cfg.analitica_frontend_origins
    ):
        raise HTTPException(403, "Origen no autorizado")
    if request.headers.get("sec-fetch-site") not in (None, "same-origin"):
        raise HTTPException(403, "Solicitud entre orígenes no permitida")


def navegacion_valida(request: Request) -> None:
    if (
        request.headers.getlist("sec-fetch-site") != ["same-origin"]
        or request.headers.getlist("sec-fetch-dest") != ["iframe"]
        or request.headers.getlist("sec-fetch-mode") != ["navigate"]
    ):
        raise HTTPException(403, "Requiere navegación de iframe desde el mismo origen")


def csrf(identificador: str, cfg: Settings) -> str:
    if cfg.analitica_session_key is None:
        raise HTTPException(503, "Sesiones de Analítica no configuradas")
    return hmac.new(
        cfg.analitica_session_key.get_secret_value().encode(),
        b"analitica-csrf-v1:" + identificador.encode(),
        hashlib.sha256,
    ).hexdigest()


def borrar_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path=RUTA, secure=True, httponly=True, samesite="Strict")


class RutaAnalitica(APIRoute):
    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def manejar(request: Request) -> Response:
            try:
                response = await original(request)
            except (DomainError, TokenInvalido, HTTPException) as exc:
                estado = getattr(exc, "status_code", 401)
                codigo = getattr(exc, "code", f"http_{estado}")
                titulo = getattr(exc, "title", None) or (
                    exc.detail
                    if isinstance(exc, HTTPException)
                    else "Credencial de Analítica inválida"
                )
                response = JSONResponse(
                    {
                        "type": f"https://citypass.local/errors/{codigo}",
                        "title": titulo,
                        "status": estado,
                        "code": codigo,
                        "instance": request.url.path,
                    },
                    status_code=estado,
                    media_type="application/problem+json",
                    headers=getattr(exc, "headers", None),
                )
                if estado == 401:
                    response.headers["WWW-Authenticate"] = "Bearer"
                if getattr(request.state, "analitica_borrar_cookie", False):
                    borrar_cookie(response)
            if not any(
                p.strip().lower() == "no-store"
                for v in response.headers.getlist("cache-control")
                for p in parse_http_list(v)
            ):
                response.headers.append("Cache-Control", "no-store")
            return response

        return manejar
