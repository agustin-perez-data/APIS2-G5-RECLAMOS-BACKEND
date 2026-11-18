"""Bearer authorization for Analytics; cookie sessions are integrated separately."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import bearer_scheme
from app.core.analitica_auth import autenticar_admin_analitica
from app.core.security import CurrentUser, TokenInvalido


async def get_admin_analitica(
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser:
    try:
        if credenciales is None or not credenciales.credentials:
            raise TokenInvalido("Falta el Bearer humano")
        return autenticar_admin_analitica(credenciales.credentials)
    except TokenInvalido as exc:
        raise HTTPException(
            status_code=401,
            detail="Token de Analítica inválido o ausente",
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        ) from exc


AdminAnaliticaDep = Annotated[CurrentUser, Depends(get_admin_analitica)]
