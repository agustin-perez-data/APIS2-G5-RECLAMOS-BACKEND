"""Development login: temporary stand-in for the Federated Login (Group 2).

**This is scaffolding, not a feature.** `CLAUDE.md` states that this module
never mints tokens, and that rule still holds for production code: the router
is only mounted when `AUTH_DEV_LOGIN_ENABLED=true`, which `Settings` refuses to
accept outside a development environment.

Why it exists: Entrega 1 demoes the claims module on its own, with the identity
service not yet available. Handing out real HS256 tokens - instead of bypassing
authentication with `AUTH_ENABLED=false` - keeps the security layer exercised
end to end and lets the front end integrate against the definitive flow
(login -> token -> `Authorization` header).

Removal criteria: as soon as Group 2 exposes its issuer, delete this file, drop
the include in `router.py` and point `JWT_JWKS_URL` at them. Nothing else in
the service has to change: every endpoint already validates tokens the same way
regardless of who signed them.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, HTTPException, status

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import Roles
from app.schemas.auth import LoginPedido, TokenOut, UsuarioOut

log = get_logger(__name__)

router = APIRouter(prefix="/auth/dev", tags=["auth (desarrollo)"])


@dataclass(frozen=True, slots=True)
class UsuarioDev:
    """A fixture user. Roles are split on purpose, see the note below."""

    usuario: str
    password: str
    sub: str
    nombre: str
    roles: tuple[str, ...] = ()

    @property
    def email(self) -> str:
        return f"{self.usuario}@citypass.local"


# One user per role, never one user holding every role: the demo has to show
# that an operator cannot reach the metrics, which is only visible when the
# roles are actually separate.
USUARIOS_DEV: dict[str, UsuarioDev] = {
    usuario.usuario: usuario
    for usuario in (
        UsuarioDev(
            usuario="vecino1",
            password="vecino1",
            sub="vecino-1",
            nombre="Vecina Perez",
            roles=(Roles.CIUDADANO,),
        ),
        UsuarioDev(
            usuario="operador1",
            password="operador1",
            sub="operador-1",
            nombre="Operador Municipal",
            roles=(Roles.OPERADOR,),
        ),
        UsuarioDev(
            usuario="admin1",
            password="admin1",
            sub="admin-1",
            nombre="Administrador del Modulo",
            roles=(Roles.OPERADOR, Roles.ADMIN),
        ),
    )
}


def _emitir_token(usuario: UsuarioDev) -> tuple[str, int]:
    """Sign a token with the same claims Group 2 will send."""
    ahora = datetime.now(UTC)
    vence_en = timedelta(hours=settings.auth_dev_token_horas)
    token = jwt.encode(
        {
            "sub": usuario.sub,
            "roles": list(usuario.roles),
            "email": usuario.email,
            "name": usuario.nombre,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": ahora,
            "exp": ahora + vence_en,
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return token, int(vence_en.total_seconds())


@router.post(
    "/login",
    response_model=TokenOut,
    summary="Login de desarrollo (usuarios de prueba)",
    description=(
        "**Solo para la Entrega 1.** Valida contra una lista fija de usuarios y "
        "devuelve un JWT con el mismo formato que va a emitir el Login Federado "
        "del Grupo 2. Credenciales incorrectas devuelven 401."
    ),
    responses={401: {"description": "Usuario o contrasena incorrectos"}},
)
async def login(datos: LoginPedido) -> TokenOut:
    usuario = USUARIOS_DEV.get(datos.usuario.strip().lower())

    # compare_digest rather than `==`: the habit costs nothing and keeps the
    # shape of the check right for whoever copies it later.
    if usuario is None or not secrets.compare_digest(usuario.password, datos.password):
        log.warning("auth.dev.login_fallido", usuario=datos.usuario)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario o contrasena incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token, expira_en = _emitir_token(usuario)
    log.info("auth.dev.login_ok", usuario=usuario.usuario, roles=list(usuario.roles))

    return TokenOut(
        access_token=token,
        expires_in=expira_en,
        usuario=UsuarioOut(
            id=usuario.sub,
            nombre=usuario.nombre,
            email=usuario.email,
            roles=list(usuario.roles),
        ),
    )


@router.get(
    "/usuarios",
    response_model=list[UsuarioOut],
    summary="Usuarios de prueba disponibles",
    description=(
        "Lista los usuarios de la Entrega 1 **sin sus contrasenas**, para que el "
        "front no tenga que duplicar la lista. Desaparece junto con el resto de "
        "este router."
    ),
)
async def usuarios() -> list[UsuarioOut]:
    return [
        UsuarioOut(
            id=usuario.sub,
            nombre=usuario.nombre,
            email=usuario.email,
            roles=list(usuario.roles),
        )
        for usuario in USUARIOS_DEV.values()
    ]
