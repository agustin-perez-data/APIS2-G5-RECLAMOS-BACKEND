"""The internal side of a claim does not reach neighbours through the API (ADR 0020)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import CIUDADANO_ID, OPERADOR_ID

RECLAMO = {
    "titulo": "Luminaria apagada en la plaza",
    "descripcion": "El foco del poste no enciende hace dos semanas y quedo todo oscuro",
}


@pytest.fixture
async def reclamo_atendido(client: AsyncClient, auth, token_ciudadano, token_operador) -> str:
    """A claim filed by a neighbour, then assigned and answered by an operator."""
    alta = await client.post("/api/v1/reclamos", json=RECLAMO, headers=auth(token_ciudadano))
    assert alta.status_code == 201, alta.text
    reclamo_id = alta.json()["id"]

    asignacion = await client.patch(
        f"/api/v1/reclamos/{reclamo_id}/estado",
        json={
            "estado": "ASIGNADO",
            "motivo": "Se deriva a la cuadrilla",
            "asignado_a": OPERADOR_ID,
            "area_responsable": "Alumbrado publico",
        },
        headers=auth(token_operador),
    )
    assert asignacion.status_code == 200, asignacion.text

    comentario = await client.post(
        f"/api/v1/reclamos/{reclamo_id}/comentarios",
        json={"texto": "La cuadrilla pasa el martes"},
        headers=auth(token_operador),
    )
    assert comentario.status_code == 201, comentario.text
    return reclamo_id


async def test_el_operador_ve_el_reclamo_completo(
    client: AsyncClient, auth, token_operador, reclamo_atendido
) -> None:
    detalle = (
        await client.get(f"/api/v1/reclamos/{reclamo_atendido}", headers=auth(token_operador))
    ).json()

    assert detalle["asignado_a"] == OPERADOR_ID
    assert [e["usuario_id"] for e in detalle["historial"]] == [CIUDADANO_ID, OPERADOR_ID]
    assert detalle["comentarios"][0]["autor_id"] == OPERADOR_ID


@pytest.mark.parametrize("token", ["token_ciudadano", "token_otro_ciudadano"])
async def test_ningun_vecino_ve_quien_atiende_el_reclamo(
    client: AsyncClient, auth, reclamo_atendido, token: str, request
) -> None:
    headers = auth(request.getfixturevalue(token))

    respuesta = await client.get(f"/api/v1/reclamos/{reclamo_atendido}", headers=headers)

    assert respuesta.status_code == 200
    detalle = respuesta.json()
    assert detalle["asignado_a"] is None
    assert detalle["area_responsable"] == "Alumbrado publico"
    assert [e["usuario_id"] for e in detalle["historial"]] == [CIUDADANO_ID, "municipio"]
    assert detalle["historial"][1]["motivo"] == "Se deriva a la cuadrilla"
    (comentario,) = detalle["comentarios"]
    assert comentario["autor_id"] == "municipio"
    assert comentario["autor_nombre"] == "El municipio"
    assert comentario["es_oficial"] is True
    assert comentario["texto"] == "La cuadrilla pasa el martes"
    # The operator's id must not be anywhere in what the neighbour received.
    assert OPERADOR_ID not in respuesta.text


async def test_el_historial_suelto_tampoco_expone_al_operador(
    client: AsyncClient, auth, token_otro_ciudadano, token_operador, reclamo_atendido
) -> None:
    ruta = f"/api/v1/reclamos/{reclamo_atendido}/historial"

    del_vecino = await client.get(ruta, headers=auth(token_otro_ciudadano))
    del_operador = await client.get(ruta, headers=auth(token_operador))

    assert [e["usuario_id"] for e in del_vecino.json()] == [CIUDADANO_ID, "municipio"]
    assert [e["usuario_id"] for e in del_operador.json()] == [CIUDADANO_ID, OPERADOR_ID]


async def test_los_comentarios_sueltos_tampoco_exponen_al_operador(
    client: AsyncClient, auth, token_otro_ciudadano, token_operador, reclamo_atendido
) -> None:
    ruta = f"/api/v1/reclamos/{reclamo_atendido}/comentarios"

    del_vecino = await client.get(ruta, headers=auth(token_otro_ciudadano))
    del_operador = await client.get(ruta, headers=auth(token_operador))

    assert OPERADOR_ID not in del_vecino.text
    assert del_vecino.json()[0]["autor_nombre"] == "El municipio"
    assert del_operador.json()[0]["autor_id"] == OPERADOR_ID


async def test_el_comentario_de_un_vecino_conserva_su_autor(
    client: AsyncClient, auth, token_ciudadano, token_otro_ciudadano, reclamo_atendido
) -> None:
    await client.post(
        f"/api/v1/reclamos/{reclamo_atendido}/comentarios",
        json={"texto": "A mi me pasa lo mismo"},
        headers=auth(token_otro_ciudadano),
    )

    comentarios = (
        await client.get(
            f"/api/v1/reclamos/{reclamo_atendido}/comentarios", headers=auth(token_ciudadano)
        )
    ).json()

    de_vecinos = [c for c in comentarios if not c["es_oficial"]]
    assert [c["autor_id"] for c in de_vecinos] == ["ciudadano-002"]


async def test_un_reclamo_ajeno_se_sigue_pudiendo_leer(
    client: AsyncClient, auth, token_otro_ciudadano, reclamo_atendido
) -> None:
    # Endorsing somebody else's claim needs reading it: hiding fields must
    # not turn into hiding the claim.
    respuesta = await client.get(
        f"/api/v1/reclamos/{reclamo_atendido}", headers=auth(token_otro_ciudadano)
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["titulo"] == RECLAMO["titulo"]
    assert respuesta.json()["estado"] == "ASIGNADO"
