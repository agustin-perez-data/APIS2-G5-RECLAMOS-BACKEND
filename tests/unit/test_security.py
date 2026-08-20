"""Tests for JWT validation and role extraction."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import Roles, TokenInvalido, decode_token, user_from_claims
from tests.conftest import crear_token


def test_token_valido_se_decodifica() -> None:
    claims = decode_token(crear_token("u-1", [Roles.CIUDADANO]))
    assert claims["sub"] == "u-1"


def test_token_expirado_es_rechazado() -> None:
    vencido = crear_token("u-1", [Roles.CIUDADANO], expira_en=timedelta(seconds=-10))
    with pytest.raises(TokenInvalido):
        decode_token(vencido)


def test_firma_invalida_es_rechazada() -> None:
    ajeno = jwt.encode(
        {"sub": "u-1", "aud": settings.jwt_audience, "iss": settings.jwt_issuer, "exp": 9999999999},
        "otro-secreto",
        algorithm="HS256",
    )
    with pytest.raises(TokenInvalido):
        decode_token(ajeno)


def test_audiencia_incorrecta_es_rechazada() -> None:
    otro = jwt.encode(
        {"sub": "u-1", "aud": "otra-app", "iss": settings.jwt_issuer, "exp": 9999999999},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(TokenInvalido):
        decode_token(otro)


def test_token_sin_sub_es_rechazado() -> None:
    sin_sub = jwt.encode(
        {"aud": settings.jwt_audience, "iss": settings.jwt_issuer, "exp": 9999999999},
        settings.jwt_secret,
        algorithm="HS256",
    )
    with pytest.raises(TokenInvalido):
        decode_token(sin_sub)


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "u-1", "roles": ["operador"]},
        {"sub": "u-1", "roles": "operador ciudadano"},
        # Keycloak-style nesting: several IdPs ship roles this way.
        {"sub": "u-1", "realm_access": {"roles": ["OPERADOR"]}},
    ],
)
def test_extraccion_de_roles_en_distintos_formatos(claims) -> None:
    usuario = user_from_claims(claims)
    assert usuario.tiene_rol(Roles.OPERADOR)
    assert usuario.es_staff


def test_ciudadano_no_es_staff() -> None:
    usuario = user_from_claims({"sub": "u-1", "roles": ["ciudadano"]})
    assert not usuario.es_staff


def test_sin_claim_de_roles_queda_sin_permisos() -> None:
    usuario = user_from_claims({"sub": "u-1"})
    assert usuario.roles == frozenset()
    assert not usuario.es_staff
