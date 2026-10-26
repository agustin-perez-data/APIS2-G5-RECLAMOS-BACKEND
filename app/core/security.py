"""Token validation for the two identity issuers this module trusts.

Group 2's Federated Login authenticates **municipal staff only**; their IdP does
not cover neighbours, so this module registers and authenticates citizens itself
and signs their tokens (see ADR 0011). That means two issuers coexist, and a
token has to be validated against the one that actually minted it:

* **Staff** - Group 2's IdP. RS256 against their JWKS in production, HS256 with a
  shared secret while the development login stands in for them.
* **Citizens** - this service. Always HS256 with our own secret.

A token is routed by its `iss` claim, which is read *unverified* only to pick the
configuration; `jwt.decode` then verifies everything against it, `issuer`
included, so a forged `iss` never survives. Each issuer declares a single
algorithm, which is what closes the algorithm-confusion hole: the IdP's public
RS256 key cannot be replayed as an HS256 secret.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.core.config import Settings, settings


class Roles:
    """Roles the application authorises on."""

    CIUDADANO = "ciudadano"
    OPERADOR = "operador"
    ADMIN = "admin"


class OrigenIdentidad(StrEnum):
    """Which issuer vouched for an identity."""

    IDP = "idp"  # Group 2: municipal staff
    LOCAL = "local"  # citizens registered in this module


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """A validated identity, as the application layer consumes it."""

    id: str
    email: str | None = None
    nombre: str | None = None
    roles: frozenset[str] = frozenset()
    claims: dict[str, Any] | None = None
    # Provenance, for auditing and defence in depth. Authorisation still goes
    # through roles: no endpoint branches on this.
    origen: OrigenIdentidad = OrigenIdentidad.IDP

    def tiene_rol(self, *roles: str) -> bool:
        return bool(self.roles.intersection(roles))

    @property
    def es_staff(self) -> bool:
        """Municipal operators and administrators."""
        return self.tiene_rol(Roles.OPERADOR, Roles.ADMIN)


class TokenInvalido(Exception):
    """The token failed validation (signature, expiry, audience, ...)."""


@dataclass(frozen=True, slots=True)
class EmisorJWT:
    """Everything needed to validate the tokens of one issuer."""

    issuer: str
    audience: str
    algorithm: str  # exactly one, never a list
    origen: OrigenIdentidad
    roles_claim: str = "roles"
    secret: str | None = None
    jwks_url: str | None = None
    # Empty means "no restriction". Non-empty is a hard whitelist applied after
    # the group mapping, so a role this issuer may not grant is dropped even if
    # the token asks for it.
    roles_permitidos: frozenset[str] = frozenset()
    grupos_a_roles: dict[str, str] = field(default_factory=dict)
    # Claims that must be present with an exact value, e.g. {"token_use": "human"}.
    claims_requeridos: dict[str, str] = field(default_factory=dict)


def _emisor_staff(cfg: Settings) -> EmisorJWT:
    grupos: dict[str, str] = {}
    for grupo in cfg.jwt_staff_grupos_operador:
        grupos[grupo.strip().lower()] = Roles.OPERADOR
    for grupo in cfg.jwt_staff_grupos_admin:
        grupos[grupo.strip().lower()] = Roles.ADMIN

    requeridos: dict[str, str] = {}
    if cfg.jwt_staff_estricto and cfg.jwt_token_use_esperado:
        requeridos["token_use"] = cfg.jwt_token_use_esperado

    return EmisorJWT(
        issuer=cfg.jwt_issuer or "",
        audience=cfg.jwt_audience or "",
        algorithm=cfg.jwt_algorithm,
        origen=OrigenIdentidad.IDP,
        roles_claim=cfg.jwt_roles_claim,
        secret=cfg.jwt_secret,
        jwks_url=cfg.jwt_jwks_url,
        # Only once we point at the real IdP. While the development login is the
        # issuer it also mints `ciudadano` tokens, and restricting them here
        # would break every existing test and demo.
        roles_permitidos=(
            frozenset({Roles.OPERADOR, Roles.ADMIN}) if cfg.jwt_staff_estricto else frozenset()
        ),
        grupos_a_roles=grupos,
        claims_requeridos=requeridos,
    )


def _emisor_ciudadanos(cfg: Settings) -> EmisorJWT:
    return EmisorJWT(
        issuer=cfg.jwt_ciudadanos_issuer,
        audience=cfg.jwt_ciudadanos_audience,
        # Not configurable: an .env must not be able to weaken it.
        algorithm="HS256",
        origen=OrigenIdentidad.LOCAL,
        roles_claim="roles",
        secret=cfg.jwt_ciudadanos_secret,
        # A token we signed can only ever be a neighbour. Even if a bug of ours
        # put "admin" in the claim, it is dropped here.
        roles_permitidos=frozenset({Roles.CIUDADANO}),
    )


def _emisores(cfg: Settings) -> dict[str, EmisorJWT]:
    """Issuer registry, keyed by the `iss` the tokens carry."""
    registro: dict[str, EmisorJWT] = {}
    staff = _emisor_staff(cfg)
    if staff.issuer:
        registro[staff.issuer] = staff
    if cfg.ciudadanos_auth_enabled:
        ciudadanos = _emisor_ciudadanos(cfg)
        registro[ciudadanos.issuer] = ciudadanos
    return registro


# urllib announces itself as `Python-urllib/<version>`, and the IdP sits behind
# Cloudflare, which answers that user agent with a 403 (error 1010, "browser
# signature banned"). PyJWKClient fetches the JWKS with urllib, so leaving the
# default user agent means every staff token fails to validate with a confusing
# "Fail to fetch data from the url" -- verified against their endpoint on
# 2026-10-26: curl, a browser and this user agent all get a 200, `Python-urllib`
# alone gets the 403.
_JWKS_USER_AGENT = "citypass-reclamos/1.0"

# Their service belongs to another group and is deployed on free tier. The
# default is 30 s, and this fetch is blocking (see ADR 0012), so a slow response
# would hold the event loop for half a minute.
_JWKS_TIMEOUT = 5.0


@lru_cache
def _jwks_client(url: str) -> PyJWKClient:
    # Cache the issuer's public keys so we don't hit it on every request.
    return PyJWKClient(
        url,
        cache_keys=True,
        headers={"User-Agent": _JWKS_USER_AGENT},
        timeout=_JWKS_TIMEOUT,
    )


def _signing_key(token: str, emisor: EmisorJWT) -> Any:
    if emisor.algorithm.startswith(("RS", "ES")):
        if not emisor.jwks_url:
            raise TokenInvalido("JWT_JWKS_URL es obligatorio para algoritmos asimetricos")
        return _jwks_client(emisor.jwks_url).get_signing_key_from_jwt(token).key
    if not emisor.secret:
        raise TokenInvalido(f"el emisor '{emisor.issuer}' no tiene secreto configurado")
    return emisor.secret


def _emisor_para(token: str, cfg: Settings) -> EmisorJWT:
    """Pick the issuer from the unverified `iss`.

    Reading a claim before checking the signature is only safe because nothing
    is trusted from it: it selects a configuration, and `jwt.decode` then pins
    `issuer` to that same value, so a token claiming someone else's `iss` fails
    on the signature anyway.
    """
    try:
        sin_verificar = jwt.decode(
            token,
            options={
                "verify_signature": False,
                "verify_exp": False,
                "verify_aud": False,
                "verify_iss": False,
            },
        )
    except jwt.PyJWTError as exc:
        raise TokenInvalido(str(exc)) from exc

    declarado = sin_verificar.get("iss")
    if not declarado:
        raise TokenInvalido("el token no declara emisor (claim 'iss')")
    emisor = _emisores(cfg).get(str(declarado))
    if emisor is None:
        raise TokenInvalido(f"emisor desconocido: '{declarado}'")
    return emisor


def decode_token(token: str, cfg: Settings | None = None) -> dict[str, Any]:
    """Validate signature, expiry, issuer and audience. Returns the claims."""
    cfg = cfg or settings
    emisor = _emisor_para(token, cfg)
    try:
        claims = jwt.decode(
            token,
            _signing_key(token, emisor),
            algorithms=[emisor.algorithm],
            audience=emisor.audience,
            issuer=emisor.issuer,
            options={
                "require": ["exp", "sub", "iss"],
                "verify_aud": bool(emisor.audience),
                "verify_iss": True,
            },
        )
    except TokenInvalido:
        raise
    except jwt.PyJWTError as exc:
        raise TokenInvalido(str(exc)) from exc

    for claim, esperado in emisor.claims_requeridos.items():
        if claims.get(claim) != esperado:
            raise TokenInvalido(f"el claim '{claim}' deberia valer '{esperado}'")
    return claims


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


def _roles_del_emisor(claims: dict[str, Any], emisor: EmisorJWT) -> frozenset[str]:
    """Turn the token's raw claim into the roles this issuer may grant."""
    crudos = _extraer_roles(claims, emisor.roles_claim)
    if emisor.grupos_a_roles:
        # The IdP sends LDAP group names, not roles. A group nobody mapped
        # grants nothing: an employee with no groups assigned yet must not end
        # up with staff access by default.
        crudos = frozenset(
            emisor.grupos_a_roles[grupo] for grupo in crudos if grupo in emisor.grupos_a_roles
        )
    if emisor.roles_permitidos:
        crudos = crudos & emisor.roles_permitidos
    return crudos


def user_from_claims(claims: dict[str, Any], cfg: Settings | None = None) -> CurrentUser:
    """Map already-validated claims onto an identity.

    Callers reach here through `decode_token`, which pinned the issuer, so the
    `iss` is present and known. The staff issuer is the fallback for claims
    built by hand: this is a pure mapping and the trust decision was taken
    upstream, not here.
    """
    cfg = cfg or settings
    emisor = _emisores(cfg).get(str(claims.get("iss", ""))) or _emisor_staff(cfg)
    return CurrentUser(
        id=str(claims["sub"]),
        email=claims.get("email"),
        nombre=claims.get("name") or claims.get("preferred_username"),
        roles=_roles_del_emisor(claims, emisor),
        claims=claims,
        origen=emisor.origen,
    )


def emitir_token_ciudadano(
    ciudadano_id: uuid.UUID,
    email: str,
    nombre: str,
    cfg: Settings | None = None,
) -> tuple[str, int]:
    """Sign an access token for a citizen registered here. Returns (token, ttl)."""
    cfg = cfg or settings
    emisor = _emisor_ciudadanos(cfg)
    vida = timedelta(hours=cfg.jwt_ciudadanos_ttl_horas)
    emitido = int(time.time())
    payload = {
        "sub": str(ciudadano_id),
        "roles": [Roles.CIUDADANO],
        "email": email,
        "name": nombre,
        "iss": emisor.issuer,
        "aud": emisor.audience,
        "token_use": "human",
        "iat": emitido,
        "exp": emitido + int(vida.total_seconds()),
    }
    token = jwt.encode(payload, emisor.secret, algorithm=emisor.algorithm)
    return token, int(vida.total_seconds())
