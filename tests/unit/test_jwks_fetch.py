"""How we fetch Group 2's JWKS, not what we do with the keys afterwards.

Their IdP sits behind Cloudflare, which blocks urllib's default user agent with
a 403. PyJWKClient fetches over urllib, so the default made every staff token
fail to validate with a message that points at the network and not at the cause.
The server in this module imitates that behaviour so the fix stays fixed: the
real endpoint is not reachable from CI, and a test that needs it would be a
test that fails on someone else's deploy.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.config import Settings
from app.core.security import TokenInvalido, _jwks_client, decode_token

KID = "clave-de-prueba"


def _b64(valor: int) -> str:
    crudo = valor.to_bytes((valor.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(crudo).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def clave() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks(clave: rsa.RSAPrivateKey) -> bytes:
    numeros = clave.public_key().public_numbers()
    return json.dumps(
        {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": KID,
                    "n": _b64(numeros.n),
                    "e": _b64(numeros.e),
                }
            ]
        }
    ).encode()


@pytest.fixture
def idp(jwks: bytes):
    """A JWKS endpoint that rejects urllib's default user agent, like theirs."""
    vistos: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802  (urllib's own naming)
            agente = self.headers.get("User-Agent", "")
            vistos.append(agente)
            if agente.startswith("Python-urllib"):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"error code: 1010")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(jwks)))
            self.end_headers()
            self.wfile.write(jwks)

        def log_message(self, *args: object) -> None:
            pass  # keep pytest's output clean

    servidor = HTTPServer(("127.0.0.1", 0), Handler)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    puerto = servidor.server_address[1]
    try:
        yield f"http://127.0.0.1:{puerto}/.well-known/jwks.json", vistos
    finally:
        servidor.shutdown()
        servidor.server_close()


def _config(url: str) -> Settings:
    return Settings(
        environment="test",
        auth_dev_login_enabled=False,
        jwt_algorithm="RS256",
        jwt_jwks_url=url,
        jwt_issuer="https://idp.citypass.local",
        jwt_audience="citypass-reclamos-api",
        jwt_roles_claim="groups",
        jwt_staff_estricto=True,
        jwt_token_use_esperado="human",
        jwt_staff_grupos_operador=["operadores"],
        jwt_ciudadanos_secret="secreto-de-ciudadanos",
    )


def _token(clave: rsa.RSAPrivateKey, cfg: Settings) -> str:
    ahora = int(time.time())
    return jwt.encode(
        {
            "sub": "U000003",
            "iss": cfg.jwt_issuer,
            "aud": cfg.jwt_audience,
            "token_use": "human",
            "groups": ["operadores"],
            "iat": ahora,
            "exp": ahora + 300,
        },
        clave,
        algorithm="RS256",
        headers={"kid": KID},
    )


def test_el_jwks_se_baja_con_un_user_agent_propio(idp, clave) -> None:
    url, vistos = idp
    cfg = _config(url)

    claims = decode_token(_token(clave, cfg), cfg)

    assert claims["sub"] == "U000003"
    assert vistos, "nunca se pidio el JWKS"
    assert not any(a.startswith("Python-urllib") for a in vistos)


def test_el_servidor_de_prueba_rechaza_el_user_agent_de_urllib(idp) -> None:
    # Control for the test above: without this, a server that answered everyone
    # would make the previous assertion pass even with the bug back in place.
    url, _ = idp
    from jwt import PyJWKClient

    with pytest.raises(Exception, match="403"):
        PyJWKClient(url).get_jwk_set(refresh=True)


def test_el_fetch_del_jwks_tiene_un_timeout_acotado() -> None:
    # Their service is on a free tier and the fetch blocks the event loop, so
    # urllib's 30 s default would stall every request behind it.
    cliente = _jwks_client("https://ejemplo.invalido/.well-known/jwks.json")

    assert 0 < cliente.timeout <= 10


def test_un_jwks_inalcanzable_se_traduce_a_token_invalido(clave) -> None:
    # Port 1 has nothing listening: the connection error has to surface as a
    # 401 and not as an unhandled 500.
    cfg = _config("http://127.0.0.1:1/.well-known/jwks.json")

    with pytest.raises(TokenInvalido):
        decode_token(_token(clave, cfg), cfg)
