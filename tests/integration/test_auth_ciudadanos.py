"""Tests of the citizens' registration and login.

Group 2's IdP authenticates municipal staff only, so these are the accounts the
neighbours who file claims actually use (ADR 0011).
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Ciudadano

REGISTRO = "/api/v1/auth/ciudadanos/registro"
LOGIN = "/api/v1/auth/ciudadanos/login"

CUENTA = {
    "email": "vecina@ejemplo.com",
    "password": "una-clave-larga",
    "nombre": "Vecina de Palermo",
}


async def registrar(client: AsyncClient, **overrides):
    return await client.post(REGISTRO, json={**CUENTA, **overrides})


async def test_el_registro_crea_la_cuenta_y_devuelve_token(client: AsyncClient) -> None:
    respuesta = await registrar(client)

    assert respuesta.status_code == 201, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["token_type"] == "bearer"
    assert cuerpo["access_token"]
    assert cuerpo["usuario"]["roles"] == ["ciudadano"]
    assert cuerpo["usuario"]["email"] == CUENTA["email"]


async def test_el_email_duplicado_devuelve_409(client: AsyncClient) -> None:
    await registrar(client)
    respuesta = await registrar(client, nombre="Otra persona")

    assert respuesta.status_code == 409
    assert respuesta.headers["content-type"].startswith("application/problem+json")


async def test_el_email_no_distingue_mayusculas(client: AsyncClient) -> None:
    await registrar(client, email="Vecina@Ejemplo.COM")

    respuesta = await client.post(
        LOGIN, json={"email": "vecina@ejemplo.com", "password": CUENTA["password"]}
    )

    assert respuesta.status_code == 200


async def test_ninguna_respuesta_expone_el_hash(client: AsyncClient) -> None:
    registro = await registrar(client)
    login = await client.post(
        LOGIN, json={"email": CUENTA["email"], "password": CUENTA["password"]}
    )

    for respuesta in (registro, login):
        assert "password" not in respuesta.text
        assert "scrypt" not in respuesta.text


async def test_el_token_del_vecino_sirve_para_crear_un_reclamo(client: AsyncClient) -> None:
    """End to end: the token this router mints passes the normal validation."""
    cuenta = (await registrar(client)).json()

    respuesta = await client.post(
        "/api/v1/reclamos",
        json={
            "titulo": "Auto estacionado sobre la ciclovia",
            "descripcion": "Hay un auto arriba de la bicisenda y no se puede pasar",
            "barrio": "Palermo",
        },
        headers={"Authorization": f"Bearer {cuenta['access_token']}"},
    )

    assert respuesta.status_code == 201, respuesta.text
    # The claim is tied to the citizen's own id, not to anything from the IdP.
    assert respuesta.json()["ciudadano_id"] == cuenta["usuario"]["id"]


async def test_el_vecino_no_entra_a_las_rutas_del_staff(client: AsyncClient) -> None:
    token = (await registrar(client)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    bandeja = await client.get("/api/v1/reclamos/bandeja", headers=headers)
    estadisticas = await client.get("/api/v1/reclamos/estadisticas", headers=headers)

    assert bandeja.status_code == 403
    assert estadisticas.status_code == 403


async def test_la_password_incorrecta_y_el_email_inexistente_son_indistinguibles(
    client: AsyncClient,
) -> None:
    # Telling them apart would turn the login into a directory of who is
    # registered, so the two answers have to be byte for byte the same.
    await registrar(client)

    mala_password = await client.post(
        LOGIN, json={"email": CUENTA["email"], "password": "no-es-la-clave"}
    )
    desconocido = await client.post(
        LOGIN, json={"email": "nadie@ejemplo.com", "password": "no-es-la-clave"}
    )

    assert mala_password.status_code == desconocido.status_code == 401
    assert mala_password.json() == desconocido.json()


async def test_el_vecino_dado_de_baja_no_puede_entrar(
    client: AsyncClient, session: AsyncSession
) -> None:
    await registrar(client)
    ciudadano = (
        await session.execute(select(Ciudadano).where(Ciudadano.email == CUENTA["email"]))
    ).scalar_one()
    ciudadano.activo = False
    await session.commit()

    respuesta = await client.post(
        LOGIN, json={"email": CUENTA["email"], "password": CUENTA["password"]}
    )

    assert respuesta.status_code == 401


async def test_la_password_corta_devuelve_422(client: AsyncClient) -> None:
    respuesta = await registrar(client, password="corta")
    assert respuesta.status_code == 422


async def test_el_email_invalido_devuelve_422(client: AsyncClient) -> None:
    respuesta = await registrar(client, email="no-es-un-mail")
    assert respuesta.status_code == 422
