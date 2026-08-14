"""Validation of the JWTs issued by the Federated Login module (Group 2).

This service is a *consumer* of identity: it never mints tokens nor stores user
credentials. Both schemes the issuer may expose are supported:

* HS256 with a shared secret (handy for local development).
* RS256, verifying the signature against the issuer's published JWKS.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import Settings, settings


class Roles:
    """Roles expected in the token's `roles` claim."""

    CIUDADANO = "ciudadano"
    OPERADOR = "operador"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """A validated identity, as the application layer consumes it."""

    id: str
    email: str | None = None
    nombre: str | None = None
    roles: frozenset[str] = frozenset()
    claims: dict[str, Any] | None = None

    def tiene_rol(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))

    @property
    def es_staff(self) -> bool:
        """Municipal operators and administrators."""
        return self.tiene_rol(Roles.OPERADOR, Roles.ADMIN)


class TokenInvalido(Exception):
    """The token failed validation (signature, expiry, audience, ...)."""


@lru_cache
def _jwks_client(url: str) -> PyJWKClient:
    # Cache the issuer's public keys so we don't hit it on every request.
    return PyJWKClient(url, cache_keys=True)


def _signing_key(token: str, cfg: Settings) -> Any:
    if cfg.jwt_algorithm.startswith("RS") or cfg.jwt_algorithm.startswith("ES"):
        if not cfg.jwt_jwks_url:
            raise TokenInvalido("JWT_JWKS_URL es obligatorio para algoritmos asimetricos")
        return _jwks_client(cfg.jwt_jwks_url).get_signing_key_from_jwt(token).key
    return cfg.jwt_secret


def decode_token(token: str, cfg: Settings | None = None) -> dict[str, Any]:
    """Validate signature, expiry, issuer and audience. Returns the claims."""
    cfg = cfg or settings
    try:
        return jwt.decode(
            token,
            _signing_key(token, cfg),
            algorithms=[cfg.jwt_algorithm],
            audience=cfg.jwt_audience,
            issuer=cfg.jwt_issuer,
            options={
                "require": ["exp", "sub"],
                "verify_aud": cfg.jwt_audience is not None,
                "verify_iss": cfg.jwt_issuer is not None,
            },
        )
    except TokenInvalido:
        raise
    except jwt.PyJWTError as exc:
        raise TokenInvalido(str(exc)) from exc


def _extraer_roles(claims: dict[str, Any], claim_name: str) -> frozenset[str]:
    """Normalise the roles claim.

    Accepts a list, a space/comma separated string, or the nested
    `realm_access.roles` shape that several identity providers use.
    """
    raw = claims.get(claim_name)
    if raw is None:
        realm = claims.get("realm_access")
        if isinstance(realm, dict):
            raw = realm.get("roles")
    if raw is None:
        raw = claims.get("scope")
    if isinstance(raw, str):
        return frozenset(part.lower() for part in raw.replace(",", " ").split() if part)
    if isinstance(raw, (list, tuple, set)):
        return frozenset(str(part).lower() for part in raw)
    return frozenset()


def user_from_claims(claims: dict[str, Any], cfg: Settings | None = None) -> CurrentUser:
    cfg = cfg or settings
    return CurrentUser(
        id=str(claims["sub"]),
        email=claims.get("email"),
        nombre=claims.get("name") or claims.get("preferred_username"),
        roles=_extraer_roles(claims, cfg.jwt_roles_claim),
        claims=claims,
    )
