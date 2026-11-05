"""Unit tests for citizen authentication schemas and utilities."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.auth import LoginCiudadano, RegistroCiudadano
from app.services.ciudadano_service import normalizar_email


def test_normalizar_email_elimina_espacios_y_pasa_a_minusculas() -> None:
    assert normalizar_email("  Vecina.Palermo@Ejemplo.COM  ") == "vecina.palermo@ejemplo.com"
    assert normalizar_email("usuario@dominio.org") == "usuario@dominio.org"


def test_registro_ciudadano_schema_valido() -> None:
    datos = RegistroCiudadano(email="vecino@ejemplo.com", nombre="Juan Perez")
    assert str(datos.email) == "vecino@ejemplo.com"
    assert datos.nombre == "Juan Perez"


def test_registro_ciudadano_strip_nombre_automatico() -> None:
    datos = RegistroCiudadano(email="vecino@ejemplo.com", nombre="   Ana Maria Gomez   ")
    assert datos.nombre == "Ana Maria Gomez"


def test_registro_ciudadano_rechaza_nombre_solo_espacios() -> None:
    with pytest.raises(ValidationError) as exc:
        RegistroCiudadano(email="vecino@ejemplo.com", nombre="     ")
    assert "nombre" in str(exc.value)


def test_registro_ciudadano_rechaza_nombre_corto_tras_strip() -> None:
    with pytest.raises(ValidationError) as exc:
        RegistroCiudadano(email="vecino@ejemplo.com", nombre="   X   ")
    assert "nombre" in str(exc.value)


def test_registro_ciudadano_rechaza_nombre_largo() -> None:
    with pytest.raises(ValidationError) as exc:
        RegistroCiudadano(email="vecino@ejemplo.com", nombre="A" * 121)
    assert "nombre" in str(exc.value)


def test_registro_ciudadano_rechaza_email_invalido() -> None:
    with pytest.raises(ValidationError):
        RegistroCiudadano(email="no-es-correo", nombre="Juan Perez")


def test_login_ciudadano_schema_valido_sin_password() -> None:
    datos = LoginCiudadano(email="vecino@ejemplo.com")
    assert str(datos.email) == "vecino@ejemplo.com"
    assert not hasattr(datos, "password")


def test_login_ciudadano_rechaza_email_invalido() -> None:
    with pytest.raises(ValidationError):
        LoginCiudadano(email="invalido")
