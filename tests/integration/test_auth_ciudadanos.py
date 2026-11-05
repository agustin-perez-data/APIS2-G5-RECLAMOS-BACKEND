"""Tests of the citizens' registration and login without passwords.

Group 2's IdP authenticates municipal staff only, so these are the accounts the
neighbours who file claims actually use (ADR 0011).
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.models import Ciudadano

REGISTRO = "/api/v1/auth/ciudadanos/registro"
LOGIN = "/api/v1/auth/ciudadanos/login"

CUENTA = {
    "email": "vecina@ejemplo.com",
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
    assert cuerpo["usuario"]["nombre"] == CUENTA["nombre"]
    assert cuerpo["usuario"]["id"]


async def test_el_email_duplicado_devuelve_409(client: AsyncClient) -> None:
    await registrar(client)
    respuesta = await registrar(client, nombre="Otra persona")

    assert respuesta.status_code == 409
    assert respuesta.headers["content-type"].startswith("application/problem+json")
    assert respuesta.json()["code"] == "email_ya_registrado"


async def test_el_email_no_distingue_mayusculas(client: AsyncClient) -> None:
    await registrar(client, email="Vecina@Ejemplo.COM")

    respuesta = await client.post(LOGIN, json={"email": "vecina@ejemplo.com"})

    assert respuesta.status_code == 200
    assert respuesta.json()["usuario"]["email"] == "vecina@ejemplo.com"


async def test_ninguna_respuesta_expone_hash_o_password(client: AsyncClient) -> None:
    registro = await registrar(client)
    login = await client.post(LOGIN, json={"email": CUENTA["email"]})

    assert registro.status_code == 201
    assert login.status_code == 200
    for respuesta in (registro, login):
        assert "password" not in respuesta.text
        assert "scrypt" not in respuesta.text
        assert "hash" not in respuesta.text


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
    assert respuesta.json()["ciudadano_id"] == cuenta["usuario"]["id"]


async def test_el_vecino_no_entra_a_las_rutas_del_staff(client: AsyncClient) -> None:
    token = (await registrar(client)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    bandeja = await client.get("/api/v1/reclamos/bandeja", headers=headers)
    estadisticas = await client.get("/api/v1/reclamos/estadisticas", headers=headers)

    assert bandeja.status_code == 403
    assert estadisticas.status_code == 403


async def test_el_email_inexistente_devuelve_401_con_codigo_especifico(
    client: AsyncClient,
) -> None:
    respuesta = await client.post(LOGIN, json={"email": "nadie@ejemplo.com"})
    assert respuesta.status_code == 401
    cuerpo = respuesta.json()
    assert cuerpo["code"] == "email_no_registrado"
    assert respuesta.headers["content-type"].startswith("application/problem+json")


async def test_el_login_no_crea_usuarios_automaticamente(
    client: AsyncClient, session: AsyncSession
) -> None:
    antes = (await session.execute(select(Ciudadano))).scalars().all()
    await client.post(LOGIN, json={"email": "nadie@ejemplo.com"})
    despues = (await session.execute(select(Ciudadano))).scalars().all()
    assert len(antes) == len(despues)


async def test_el_vecino_dado_de_baja_devuelve_401_cuenta_inactiva(
    client: AsyncClient, session: AsyncSession
) -> None:
    await registrar(client)
    ciudadano = (
        await session.execute(select(Ciudadano).where(Ciudadano.email == CUENTA["email"]))
    ).scalar_one()
    ciudadano.activo = False
    await session.commit()

    respuesta = await client.post(LOGIN, json={"email": CUENTA["email"]})

    assert respuesta.status_code == 401
    cuerpo = respuesta.json()
    assert cuerpo["code"] == "cuenta_inactiva"


async def test_nombre_solo_espacios_devuelve_422(client: AsyncClient) -> None:
    respuesta = await registrar(client, nombre="     ")
    assert respuesta.status_code == 422
    cuerpo = respuesta.json()
    assert cuerpo["code"] == "validacion"


async def test_nombre_demasiado_corto_tras_strip_devuelve_422(client: AsyncClient) -> None:
    respuesta = await registrar(client, nombre="  A  ")
    assert respuesta.status_code == 422


async def test_nombre_vacio_devuelve_422(client: AsyncClient) -> None:
    respuesta = await registrar(client, nombre="")
    assert respuesta.status_code == 422


async def test_nombre_conserva_espacios_interiores_y_hace_strip(
    client: AsyncClient, session: AsyncSession
) -> None:
    respuesta = await registrar(client, nombre="   Facundo Nahuel Martin   ")
    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["usuario"]["nombre"] == "Facundo Nahuel Martin"

    ciudadano = (
        await session.execute(select(Ciudadano).where(Ciudadano.email == CUENTA["email"]))
    ).scalar_one()
    assert ciudadano.nombre == "Facundo Nahuel Martin"


async def test_nombre_demasiado_largo_devuelve_422(client: AsyncClient) -> None:
    respuesta = await registrar(client, nombre="A" * 121)
    assert respuesta.status_code == 422


async def test_el_email_invalido_devuelve_422(client: AsyncClient) -> None:
    respuesta = await registrar(client, email="no-es-un-mail")
    assert respuesta.status_code == 422


async def test_login_con_email_invalido_devuelve_422(client: AsyncClient) -> None:
    respuesta = await client.post(LOGIN, json={"email": "no-es-un-mail"})
    assert respuesta.status_code == 422


async def test_el_registro_guarda_nombre_real_declarado(
    client: AsyncClient, session: AsyncSession
) -> None:
    nombre_declarado = "Facundo Martin"
    await registrar(client, nombre=nombre_declarado)

    ciudadano = (
        await session.execute(select(Ciudadano).where(Ciudadano.email == CUENTA["email"]))
    ).scalar_one()
    assert ciudadano.nombre == nombre_declarado
    assert ciudadano.nombre != CUENTA["email"].split("@")[0]


async def test_el_login_devuelve_mismo_uuid_y_nombre(client: AsyncClient) -> None:
    registro = (await registrar(client)).json()
    uuid_registrado = registro["usuario"]["id"]
    nombre_registrado = registro["usuario"]["nombre"]

    login = (await client.post(LOGIN, json={"email": CUENTA["email"]})).json()
    assert login["usuario"]["id"] == uuid_registrado
    assert login["usuario"]["nombre"] == nombre_registrado


async def test_jwt_claims_ciudadano(client: AsyncClient) -> None:
    registro = (await registrar(client)).json()
    token = registro["access_token"]
    claims = decode_token(token)

    assert claims["sub"] == registro["usuario"]["id"]
    assert claims["name"] == CUENTA["nombre"]
    assert claims["email"] == CUENTA["email"]
    assert claims["roles"] == ["ciudadano"]
    assert claims["iss"] == "citypass-reclamos"
    assert claims["aud"] == "citypass-reclamos-ciudadanos"
    assert claims["token_use"] == "human"
    assert claims["exp"] > claims["iat"]


async def test_login_actualiza_ultimo_acceso(client: AsyncClient, session: AsyncSession) -> None:
    await registrar(client)
    ciudadano = (
        await session.execute(select(Ciudadano).where(Ciudadano.email == CUENTA["email"]))
    ).scalar_one()
    assert ciudadano.ultimo_acceso_at is None

    await client.post(LOGIN, json={"email": CUENTA["email"]})

    await session.refresh(ciudadano)
    assert ciudadano.ultimo_acceso_at is not None
