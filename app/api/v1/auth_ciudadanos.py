"""Registration and login of the neighbours this module authenticates.

Group 2's Federated Login covers municipal staff only, so the people who file
claims get their account here (see ADR 0011).

These two routes are the only ones besides `/health`, the development login and
the gateway webhook that carry no identity dependency: nobody can present a
token before having one. What protects them is the rate limit, the generic
answer that makes a wrong password indistinguishable from an unknown email, and
the fact that no response ever echoes the stored hash.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import Roles
from app.db.models import Ciudadano
from app.db.session import get_session
from app.schemas.auth import LoginCiudadano, RegistroCiudadano, TokenOut, UsuarioOut
from app.services.ciudadano_service import CiudadanoService

router = APIRouter(prefix="/auth/ciudadanos", tags=["auth (ciudadanos)"])


def get_ciudadano_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CiudadanoService:
    return CiudadanoService(session)


ServicioDep = Annotated[CiudadanoService, Depends(get_ciudadano_service)]


def _respuesta(servicio: CiudadanoService, ciudadano: Ciudadano) -> TokenOut:
    token, expira_en = servicio.emitir_token(ciudadano)
    return TokenOut(
        access_token=token,
        expires_in=expira_en,
        usuario=UsuarioOut(
            id=str(ciudadano.id),
            nombre=ciudadano.nombre,
            email=ciudadano.email,
            roles=[Roles.CIUDADANO],
        ),
    )


@router.post(
    "/registro",
    response_model=TokenOut,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una cuenta de vecino",
    description=(
        "Crea la cuenta y devuelve el token directo: sin verificacion de correo "
        "no hay nada que esperar. El correo no distingue mayusculas."
    ),
    responses={409: {"description": "Ese email ya tiene una cuenta"}},
)
@limiter.limit(settings.rate_limit_registro)
async def registrar(request: Request, datos: RegistroCiudadano, servicio: ServicioDep) -> TokenOut:
    return _respuesta(servicio, await servicio.registrar(datos))


@router.post(
    "/login",
    response_model=TokenOut,
    summary="Iniciar sesion como vecino",
    description=(
        "Devuelve un JWT con el mismo formato que el del personal municipal, "
        "pero emitido por este modulo. Las credenciales incorrectas y un correo "
        "no registrado devuelven exactamente la misma respuesta."
    ),
    responses={401: {"description": "Email o contrasena incorrectos"}},
)
@limiter.limit(settings.rate_limit_login)
async def login(request: Request, datos: LoginCiudadano, servicio: ServicioDep) -> TokenOut:
    return _respuesta(servicio, await servicio.autenticar(datos))
