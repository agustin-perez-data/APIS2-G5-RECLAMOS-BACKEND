"""Analytics-only restrictions layered over the shared JWT validator."""

from __future__ import annotations

from app.core.config import Settings, settings
from app.core.exceptions import AnaliticaAccesoDenegado
from app.core.security import CurrentUser, OrigenIdentidad, Roles, TokenInvalido, user_from_claims
from app.core.security import decode_token as validar_jwt


def autenticar_admin_analitica(token: str, cfg: Settings | None = None) -> CurrentUser:
    cfg = cfg or settings
    if (
        not cfg.auth_enabled
        or cfg.jwt_algorithm != "RS256"
        or not cfg.jwt_staff_estricto
        or cfg.jwt_roles_claim != "groups"
        or cfg.jwt_audience != "citypass-reclamos-api"
        or not cfg.jwt_issuer
        or not cfg.jwt_jwks_url
        or not cfg.jwt_staff_grupos_admin
    ):
        raise TokenInvalido("Analitica requiere identidad federada RS256 de Reclamos")
    claims = validar_jwt(token, cfg)
    usuario = user_from_claims(claims, cfg)
    if usuario.origen is not OrigenIdentidad.IDP:
        raise AnaliticaAccesoDenegado()
    if claims.get("token_use") != "human":
        raise TokenInvalido("Analitica requiere token_use=human")
    if (
        not claims.get("groups")
        or not usuario.tiene_rol(Roles.ADMIN)
        or claims.get("namespace") != "com.citypass.reclamos"
    ):
        raise AnaliticaAccesoDenegado()
    return usuario
