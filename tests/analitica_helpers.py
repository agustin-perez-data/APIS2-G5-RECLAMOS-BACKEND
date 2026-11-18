"""Federated identity fixtures using real RSA signatures and a fake JWKS."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core import analitica_auth, security
from app.core.config import Settings


def entorno_federado(monkeypatch: Any) -> tuple[Settings, rsa.RSAPrivateKey]:
    clave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cfg = Settings(
        _env_file=None,
        analitica_enabled=True,
        analitica_url="https://analitica.example",
        auth_enabled=True,
        auth_dev_login_enabled=False,
        jwt_algorithm="RS256",
        jwt_jwks_url="https://login.example/jwks",
        jwt_issuer="https://idp.citypass.local",
        jwt_audience="citypass-reclamos-api",
        jwt_roles_claim="groups",
        jwt_staff_estricto=True,
        jwt_token_use_esperado="human",
        jwt_staff_grupos_admin=["reclamos-administradores"],
        jwt_staff_grupos_operador=["reclamos-operadores"],
        analitica_session_key=Fernet.generate_key().decode(),
    )
    monkeypatch.setattr(analitica_auth, "settings", cfg)
    monkeypatch.setattr(
        security,
        "_jwks_client",
        lambda _url: SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=clave.public_key())
        ),
    )
    return cfg, clave


def firmar(cfg: Settings, clave: rsa.RSAPrivateKey, **cambios: Any) -> str:
    claims = {
        "sub": "U000042",
        "iss": cfg.jwt_issuer,
        "aud": [cfg.jwt_audience],
        "exp": int(time.time()) + 900,
        "token_use": "human",
        "namespace": "com.citypass.reclamos",
        "groups": ["reclamos-administradores"],
    }
    claims.update(cambios)
    return jwt.encode(claims, clave, algorithm="RS256")
