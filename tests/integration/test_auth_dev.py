"""Tests of the development login (scaffolding for Entrega 1).

The point of these is the demo script: user 1 logs in, a wrong password does
not, and the token that comes out actually opens the endpoints for its role.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import Settings

LOGIN = "/api/v1/auth/dev/login"


async def login(client: AsyncClient, usuario: str, password: str):
    return await client.post(LOGIN, json={"usuario": usuario, "password": password})


async def test_el_usuario_de_prueba_puede_loguearse(client: AsyncClient) -> None:
    respuesta = await login(client, "vecino1", "vecino1")

    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["token_type"] == "bearer"
    assert cuerpo["access_token"]
    assert cuerpo["usuario"]["roles"] == ["ciudadano"]


async def test_la_password_incorrecta_devuelve_401(client: AsyncClient) -> None:
    respuesta = await login(client, "vecino1", "no-es-la-password")

    assert respuesta.status_code == 401
    assert respuesta.headers["content-type"].startswith("application/problem+json")


async def test_el_usuario_inexistente_devuelve_401(client: AsyncClient) -> None:
    respuesta = await login(client, "no-existe", "cualquiera")
    assert respuesta.status_code == 401


async def test_el_token_emitido_sirve_para_llamar_a_la_api(client: AsyncClient) -> None:
    """End to end: the token this router mints passes the normal validation."""
    respuesta = await login(client, "vecino1", "vecino1")
    token = respuesta.json()["access_token"]

    creado = await client.post(
        "/api/v1/reclamos",
        json={
            "titulo": "Luminaria apagada en la plaza",
            "descripcion": "El farol de la esquina no enciende desde el lunes",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert creado.status_code == 201


async def test_los_roles_de_los_usuarios_de_prueba_estan_separados(client: AsyncClient) -> None:
    """The operator must not reach the metrics; the admin must."""
    operador = (await login(client, "operador1", "operador1")).json()["access_token"]
    admin = (await login(client, "admin1", "admin1")).json()["access_token"]

    ruta = "/api/v1/reclamos/estadisticas"
    como_operador = await client.get(ruta, headers={"Authorization": f"Bearer {operador}"})
    como_admin = await client.get(ruta, headers={"Authorization": f"Bearer {admin}"})

    assert como_operador.status_code == 403
    assert como_admin.status_code == 200


async def test_la_lista_de_usuarios_no_expone_passwords(client: AsyncClient) -> None:
    respuesta = await client.get("/api/v1/auth/dev/usuarios")

    assert respuesta.status_code == 200
    usuarios = respuesta.json()
    assert {u["id"] for u in usuarios} == {"vecino-1", "operador-1", "admin-1"}
    assert all("password" not in u for u in usuarios)


def test_el_login_de_desarrollo_no_puede_encenderse_en_produccion() -> None:
    """The guard that keeps hardcoded credentials out of a real deployment."""
    with pytest.raises(ValueError, match="AUTH_DEV_LOGIN_ENABLED"):
        Settings(environment="production", auth_dev_login_enabled=True)


def test_el_login_de_desarrollo_si_puede_encenderse_en_local() -> None:
    assert Settings(environment="local", auth_dev_login_enabled=True).auth_dev_login_enabled
