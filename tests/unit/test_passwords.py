"""Tests for password hashing."""

from __future__ import annotations

from app.core.passwords import hash_password, necesita_rehash, verificar_password


def test_el_hash_no_contiene_la_password_en_claro() -> None:
    assert "LaClaveDeLaVecina" not in hash_password("LaClaveDeLaVecina")


def test_dos_hashes_de_la_misma_password_son_distintos() -> None:
    # Random salt: two neighbours with the same password must not be spottable
    # by comparing rows.
    assert hash_password("misma-clave") != hash_password("misma-clave")


def test_verifica_la_password_correcta() -> None:
    assert verificar_password("abrelasesamo", hash_password("abrelasesamo"))


def test_rechaza_la_password_incorrecta() -> None:
    assert not verificar_password("otra-cosa", hash_password("abrelasesamo"))


def test_un_hash_con_formato_desconocido_devuelve_false() -> None:
    # A corrupted row must be a failed login, never a 500.
    for basura in ("", "x", "bcrypt$algo", "scrypt$roto", "scrypt$n=a,r=b,p=c$x$y"):
        assert not verificar_password("lo-que-sea", basura)


def test_detecta_que_un_hash_con_parametros_viejos_necesita_rehash() -> None:
    viejo = hash_password("clave", n=2**12)
    assert necesita_rehash(viejo)
    assert not necesita_rehash(hash_password("clave"))


def test_un_hash_ilegible_se_considera_que_necesita_rehash() -> None:
    assert necesita_rehash("cualquier-cosa")
