"""Dependencies shared by the endpoints (session, identity, services)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import CurrentUser, Roles, TokenInvalido, decode_token, user_from_claims
from app.db.session import get_session
from app.events.producer import EventPublisher
from app.services.reclamo_service import ReclamoService

log = get_logger(__name__)

# auto_error=False so we can answer 401 with our own problem+json body.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT emitido por el Login Federado")

# Fake identity for development when AUTH_ENABLED=false. It never turns itself
# on: the flag has to be set explicitly in the .env.
USUARIO_DEV = CurrentUser(
    id="dev-user",
    email="dev@citypass.local",
    nombre="Usuario de desarrollo",
    roles=frozenset({Roles.CIUDADANO, Roles.OPERADOR, Roles.ADMIN}),
)


def get_publisher(request: Request) -> EventPublisher:
    """The publisher lives in the app lifespan (see `app/main.py`)."""
    return request.app.state.publisher


async def get_current_user(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser:
    if not settings.auth_enabled:
        return USUARIO_DEV

    if credenciales is None or not credenciales.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el header Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = decode_token(credenciales.credentials)
    except TokenInvalido as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalido: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return user_from_claims(claims)


def require_roles(*roles: str) -> Callable[[CurrentUser], CurrentUser]:
    """Dependency requiring at least one of the given roles."""

    async def _verificar(
        usuario: Annotated[CurrentUser, Depends(get_current_user)],
    ) -> CurrentUser:
        if not usuario.tiene_rol(*roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requiere alguno de estos roles: {', '.join(roles)}",
            )
        return usuario

    return _verificar


def get_reclamo_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    publisher: Annotated[EventPublisher, Depends(get_publisher)],
) -> ReclamoService:
    return ReclamoService(session, publisher)


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServiceDep = Annotated[ReclamoService, Depends(get_reclamo_service)]
UsuarioDep = Annotated[CurrentUser, Depends(get_current_user)]
StaffDep = Annotated[CurrentUser, Depends(require_roles(Roles.OPERADOR, Roles.ADMIN))]
# Metrics are management information: an operator works the inbox but does not
# get to see the module's aggregate numbers.
AdminDep = Annotated[CurrentUser, Depends(require_roles(Roles.ADMIN))]
