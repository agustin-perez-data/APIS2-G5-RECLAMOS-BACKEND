"""Tests for the two-issuer registry.

Group 2's IdP authenticates staff and this module authenticates citizens, so a
token has to be validated against whichever one minted it. These tests cover the
guarantees that keep the two apart; the plain validation rules live in
`test_security.py`.
"""

from __future__ import annotations

import time
import uuid

import jwt
import pytest

from app.core.config import Settings
from app.core.security import (
    OrigenIdentidad,
    Roles,
    TokenInvalido,
    decode_token,
    emitir_token_ciudadano,
    user_from_claims,
)


def _config(**overrides) -> Settings:
    base = {
        "environment": "test",
        "jwt_algorithm": "HS256",
        "jwt_secret": "secreto-de-staff",
        "jwt_issuer": "citypass-auth",
        "jwt_audience": "citypass",
        "jwt_ciudadanos_secret": "secreto-de-ciudadanos",
    }
    base.update(overrides)
    return Settings(**base)


def _token_staff(cfg: Settings, **claims) -> str:
    payload = {
        "sub": "U000042",
        "iss": cfg.jwt_issuer,
        "aud": cfg.jwt_audience,
        "exp": int(time.time()) + 3600,
    }
    payload.update(claims)
    return jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")


# --- Keeping the two issuers apart ---------------------------------------------
def test_el_token_de_ciudadano_se_valida_contra_el_emisor_local() -> None:
    cfg = _config()
    token, _ = emitir_token_ciudadano(uuid.uuid4(), "vecina@ejemplo.com", "Vecina", cfg)

    usuario = user_from_claims(decode_token(token, cfg), cfg)

    assert usuario.origen is OrigenIdentidad.LOCAL
    assert usuario.roles == frozenset({Roles.CIUDADANO})


def test_el_token_de_ciudadano_nunca_obtiene_rol_de_operador() -> None:
    # Even if a bug of ours signed the wrong role, the issuer's whitelist drops
    # it: a token we mint can only ever speak for a neighbour.
    cfg = _config()
    payload = {
        "sub": str(uuid.uuid4()),
        "roles": [Roles.ADMIN, Roles.OPERADOR, Roles.CIUDADANO],
        "iss": cfg.jwt_ciudadanos_issuer,
        "aud": cfg.jwt_ciudadanos_audience,
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, cfg.jwt_ciudadanos_secret, algorithm="HS256")

    usuario = user_from_claims(decode_token(token, cfg), cfg)

    assert usuario.roles == frozenset({Roles.CIUDADANO})
    assert not usuario.es_staff


def test_el_token_de_ciudadano_no_pasa_con_la_audiencia_del_staff() -> None:
    cfg = _config()
    payload = {
        "sub": "x",
        "iss": cfg.jwt_ciudadanos_issuer,
        "aud": cfg.jwt_audience,
        "exp": int(time.time()) + 3600,
    }
    token = jwt.encode(payload, cfg.jwt_ciudadanos_secret, algorithm="HS256")

    with pytest.raises(TokenInvalido):
        decode_token(token, cfg)


def test_el_secreto_de_un_emisor_no_sirve_para_el_otro() -> None:
    cfg = _config()
    payload = {
        "sub": "x",
        "iss": cfg.jwt_ciudadanos_issuer,
        "aud": cfg.jwt_ciudadanos_audience,
        "exp": int(time.time()) + 3600,
    }
    # Correct issuer and audience, but signed with the staff secret.
    token = jwt.encode(payload, cfg.jwt_secret, algorithm="HS256")

    with pytest.raises(TokenInvalido):
        decode_token(token, cfg)


# --- Routing by issuer ---------------------------------------------------------
def test_un_emisor_desconocido_es_rechazado() -> None:
    cfg = _config()
    token = jwt.encode(
        {"sub": "x", "iss": "https://idp-trucho.example", "exp": int(time.time()) + 3600},
        "lo-que-sea",
        algorithm="HS256",
    )
    with pytest.raises(TokenInvalido, match="emisor desconocido"):
        decode_token(token, cfg)


def test_un_token_sin_emisor_es_rechazado() -> None:
    cfg = _config()
    token = jwt.encode({"sub": "x", "exp": int(time.time()) + 3600}, "x", algorithm="HS256")
    with pytest.raises(TokenInvalido, match="no declara emisor"):
        decode_token(token, cfg)


def test_un_token_sin_firma_es_rechazado() -> None:
    # The classic `alg: none`. Each issuer declares exactly one algorithm, so
    # anything else never reaches the signature check.
    cfg = _config()
    token = jwt.encode(
        {
            "sub": "x",
            "iss": cfg.jwt_ciudadanos_issuer,
            "aud": cfg.jwt_ciudadanos_audience,
            "exp": int(time.time()) + 3600,
        },
        None,
        algorithm="none",
    )
    with pytest.raises(TokenInvalido):
        decode_token(token, cfg)


# --- Strict mode: the real IdP -------------------------------------------------
def _config_estricta(**overrides) -> Settings:
    return _config(
        jwt_staff_estricto=True,
        jwt_token_use_esperado="human",
        jwt_roles_claim="groups",
        jwt_staff_grupos_operador=["soporte-n2"],
        jwt_staff_grupos_admin=["administradores"],
        **overrides,
    )


def test_un_token_de_servicio_no_pasa_por_persona() -> None:
    cfg = _config_estricta()
    token = _token_staff(cfg, token_use="service", groups=["soporte-n2"])
    with pytest.raises(TokenInvalido, match="token_use"):
        decode_token(token, cfg)


def test_los_grupos_ldap_se_mapean_a_roles() -> None:
    cfg = _config_estricta()
    token = _token_staff(cfg, token_use="human", groups=["administradores"])

    usuario = user_from_claims(decode_token(token, cfg), cfg)

    assert usuario.roles == frozenset({Roles.ADMIN})
    assert usuario.es_staff


def test_un_empleado_sin_grupos_conocidos_no_obtiene_permisos() -> None:
    # Group 2's guide says `groups` can legitimately come empty, and an unmapped
    # group must not grant anything either: no default staff role.
    cfg = _config_estricta()

    sin_grupos = _token_staff(cfg, token_use="human", groups=[])
    ajeno = _token_staff(cfg, token_use="human", groups=["grupo-de-otro-modulo"])

    for token in (sin_grupos, ajeno):
        usuario = user_from_claims(decode_token(token, cfg), cfg)
        assert usuario.roles == frozenset()
        assert not usuario.es_staff


def test_el_staff_no_puede_hacerse_pasar_por_ciudadano() -> None:
    cfg = _config_estricta()
    token = _token_staff(cfg, token_use="human", groups=["soporte-n2", "ciudadano"])

    usuario = user_from_claims(decode_token(token, cfg), cfg)

    assert usuario.roles == frozenset({Roles.OPERADOR})


# --- Guardas de configuracion --------------------------------------------------
def test_los_dos_emisores_no_pueden_compartir_el_issuer() -> None:
    with pytest.raises(ValueError, match="JWT_CIUDADANOS_ISSUER"):
        _config(jwt_ciudadanos_issuer="citypass-auth")


def test_los_dos_emisores_no_pueden_compartir_la_audiencia() -> None:
    with pytest.raises(ValueError, match="JWT_CIUDADANOS_AUDIENCE"):
        _config(jwt_ciudadanos_audience="citypass")


def test_el_idp_real_exige_modo_estricto() -> None:
    # Pointing at an asymmetric algorithm means the real IdP is wired, and the
    # checks that guard staff access stop being optional.
    with pytest.raises(ValueError, match="JWT_STAFF_ESTRICTO"):
        _config(jwt_algorithm="RS256")


def test_el_idp_real_exige_saber_que_token_use_esperar() -> None:
    with pytest.raises(ValueError, match="JWT_TOKEN_USE_ESPERADO"):
        _config(jwt_algorithm="RS256", jwt_staff_estricto=True)
