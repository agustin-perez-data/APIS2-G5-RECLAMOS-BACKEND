"""Session secrets never need to be stored or logged as plaintext."""

from __future__ import annotations

import base64

import pytest
from cryptography.fernet import Fernet

from app.core.analitica_session_crypto import (
    AnaliticaSessionCrypto,
    hash_identificador,
    nuevo_identificador,
)
from app.core.config import Settings
from app.core.exceptions import SesionAnaliticaInvalida


def test_identificadores_tienen_256_bits_y_solo_se_persiste_el_hash() -> None:
    ids = {nuevo_identificador() for _ in range(20)}
    assert len(ids) == 20
    assert all(len(base64.urlsafe_b64decode(valor + "=")) == 32 for valor in ids)
    assert all(len(hash_identificador(valor)) == 64 for valor in ids)
    assert all(valor not in hash_identificador(valor) for valor in ids)


@pytest.mark.parametrize("identificador", ["", "a" * 42, "a" * 44, "!" * 43, "ñ" * 43])
def test_rechaza_identificadores_malformados(identificador: str) -> None:
    with pytest.raises(SesionAnaliticaInvalida):
        hash_identificador(identificador)


@pytest.mark.parametrize("clave", ["", "no-es-fernet", "ñ" * 44])
def test_rechaza_claves_invalidas_sin_exponerlas(clave: str) -> None:
    with pytest.raises(ValueError, match="ANALITICA_SESSION_KEY"):
        AnaliticaSessionCrypto(clave)


def test_cifra_con_aleatoriedad_y_vincula_el_token_a_su_sesion() -> None:
    crypto = AnaliticaSessionCrypto(Fernet.generate_key().decode())
    uno = crypto.cifrar("jwt-humano-secreto", "hash-1")
    dos = crypto.cifrar("jwt-humano-secreto", "hash-1")
    assert uno != dos
    assert b"jwt-humano-secreto" not in uno
    assert crypto.descifrar(uno, "hash-1") == "jwt-humano-secreto"
    for cifrado, contexto in [(uno[:-10] + b"alterado", "hash-1"), (uno, "hash-2")]:
        with pytest.raises(SesionAnaliticaInvalida):
            crypto.descifrar(cifrado, contexto)
    otra = AnaliticaSessionCrypto(Fernet.generate_key().decode())
    with pytest.raises(SesionAnaliticaInvalida):
        otra.descifrar(uno, "hash-1")


@pytest.mark.parametrize("ttl", [0, -1, 301])
def test_configuracion_no_permite_ttl_fuera_del_limite(ttl: int) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, analitica_session_ttl_seconds=ttl)


def test_configuracion_oculta_la_clave_de_cifrado() -> None:
    clave = Fernet.generate_key().decode()
    cfg = Settings(_env_file=None, analitica_session_key=clave)
    assert clave not in repr(cfg)
