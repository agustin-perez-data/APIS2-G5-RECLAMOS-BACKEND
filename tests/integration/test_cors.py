"""Which browser origins may call the API.

The front end on Vercel failed to log in because its domain was not allowed:
the browser blocked the preflight. These pin the rule down, including the
regex for preview deployments and the sites it must keep out.
"""

from __future__ import annotations

from httpx import AsyncClient

LOGIN = "/api/v1/auth/dev/login"


async def preflight(client: AsyncClient, origen: str):
    return await client.options(
        LOGIN,
        headers={
            "Origin": origen,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


async def test_el_front_local_puede_llamar_a_la_api(client: AsyncClient) -> None:
    respuesta = await preflight(client, "http://localhost:5173")

    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == "http://localhost:5173"


async def test_un_preview_del_front_en_vercel_esta_permitido(client: AsyncClient) -> None:
    origen = "https://reclamos-frontend-g5-git-develop-grupo5.vercel.app"
    respuesta = await preflight(client, origen)

    assert respuesta.status_code == 200
    assert respuesta.headers["access-control-allow-origin"] == origen


async def test_otro_sitio_de_vercel_no_puede_llamar_a_la_api(client: AsyncClient) -> None:
    # Anyone can deploy to *.vercel.app: the regex must not let other projects in.
    respuesta = await preflight(client, "https://sitio-cualquiera.vercel.app")

    assert respuesta.status_code == 400
    assert "access-control-allow-origin" not in respuesta.headers


async def test_un_proyecto_de_otro_equipo_con_nombre_parecido_no_entra(
    client: AsyncClient,
) -> None:
    # Same project prefix, different team slug at the end.
    respuesta = await preflight(client, "https://reclamos-frontend-g5-abc123-intruso.vercel.app")

    assert respuesta.status_code == 400
