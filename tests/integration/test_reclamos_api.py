"""HTTP-level tests: contract, status codes, and endpoint protection."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.domain.enums import CategoriaReclamo, EstadoReclamo, PrioridadReclamo
from app.events import topics
from app.events.producer import InMemoryEventPublisher

RECLAMO = {
    "titulo": "Contenedor desbordado en la esquina",
    "descripcion": "Hace tres dias que el contenedor esta lleno y hay bolsas en la vereda",
    "barrio": "Centro",
    "direccion": "San Martin 1500",
    "latitud": -34.6037,
    "longitud": -58.3816,
}


async def crear_reclamo(client: AsyncClient, headers: dict, **overrides) -> dict:
    cuerpo = {**RECLAMO, **overrides}
    respuesta = await client.post("/api/v1/reclamos", json=cuerpo, headers=headers)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


# --- Health ------------------------------------------------------------------
async def test_health_no_requiere_token(client: AsyncClient) -> None:
    respuesta = await client.get("/health")
    assert respuesta.status_code == 200
    assert respuesta.json()["status"] == "ok"


async def test_readiness_verifica_la_base(client: AsyncClient) -> None:
    respuesta = await client.get("/health/ready")
    assert respuesta.status_code == 200
    assert respuesta.json()["database"] == "ok"


# --- Security ----------------------------------------------------------------
async def test_sin_token_devuelve_401(client: AsyncClient) -> None:
    respuesta = await client.post("/api/v1/reclamos", json=RECLAMO)
    assert respuesta.status_code == 401
    assert respuesta.headers["content-type"].startswith("application/problem+json")


async def test_token_basura_devuelve_401(client: AsyncClient) -> None:
    respuesta = await client.get(
        "/api/v1/reclamos", headers={"Authorization": "Bearer no-es-un-jwt"}
    )
    assert respuesta.status_code == 401


async def test_un_ciudadano_no_puede_cambiar_estados(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    reclamo = await crear_reclamo(client, auth(token_ciudadano))

    respuesta = await client.patch(
        f"/api/v1/reclamos/{reclamo['id']}/estado",
        json={"estado": EstadoReclamo.ASIGNADO.value},
        headers=auth(token_ciudadano),
    )
    assert respuesta.status_code == 403


# --- Creation ----------------------------------------------------------------
async def test_crear_reclamo(
    client: AsyncClient, auth, token_ciudadano, publisher: InMemoryEventPublisher
) -> None:
    cuerpo = await crear_reclamo(client, auth(token_ciudadano))

    assert cuerpo["estado"] == EstadoReclamo.RECIBIDO.value
    assert cuerpo["categoria"] == CategoriaReclamo.RESIDUOS.value
    assert cuerpo["origen_clasificacion"] == "MODELO"
    assert topics.RECLAMO_CREADO in publisher.topics


async def test_crear_reclamo_invalido_devuelve_problem_detail(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    respuesta = await client.post(
        "/api/v1/reclamos",
        json={"titulo": "corto", "descripcion": "breve"},
        headers=auth(token_ciudadano),
    )
    assert respuesta.status_code == 422

    cuerpo = respuesta.json()
    assert cuerpo["title"] == "Datos de entrada invalidos"
    assert {error["campo"] for error in cuerpo["errors"]} == {"descripcion"}


async def test_el_response_trae_correlation_id(client: AsyncClient, auth, token_ciudadano) -> None:
    respuesta = await client.get("/api/v1/reclamos", headers=auth(token_ciudadano))
    assert respuesta.headers.get("X-Correlation-Id")


# --- Read --------------------------------------------------------------------
async def test_detalle_incluye_historial(client: AsyncClient, auth, token_ciudadano) -> None:
    reclamo = await crear_reclamo(client, auth(token_ciudadano))

    respuesta = await client.get(f"/api/v1/reclamos/{reclamo['id']}", headers=auth(token_ciudadano))
    assert respuesta.status_code == 200
    assert len(respuesta.json()["historial"]) == 1


async def test_detalle_inexistente_devuelve_404(client: AsyncClient, auth, token_ciudadano) -> None:
    respuesta = await client.get(f"/api/v1/reclamos/{uuid.uuid4()}", headers=auth(token_ciudadano))
    assert respuesta.status_code == 404
    assert respuesta.json()["title"] == "Reclamo no encontrado"


async def test_listado_pagina_y_filtra(client: AsyncClient, auth, token_ciudadano) -> None:
    await crear_reclamo(client, auth(token_ciudadano))
    await crear_reclamo(
        client,
        auth(token_ciudadano),
        titulo="Bache enorme en la calzada",
        descripcion="Hay un pozo profundo en el asfalto que ya rompio dos autos",
    )

    respuesta = await client.get(
        "/api/v1/reclamos",
        params={"categoria": CategoriaReclamo.BACHES.value, "size": 10},
        headers=auth(token_ciudadano),
    )
    cuerpo = respuesta.json()
    assert cuerpo["total"] == 1
    assert cuerpo["items"][0]["categoria"] == CategoriaReclamo.BACHES.value


async def test_estadisticas(client: AsyncClient, auth, token_ciudadano) -> None:
    await crear_reclamo(client, auth(token_ciudadano))

    respuesta = await client.get("/api/v1/reclamos/estadisticas", headers=auth(token_ciudadano))
    assert respuesta.status_code == 200
    assert respuesta.json()["total"] == 1


async def test_sugerencia_de_clasificacion_no_persiste(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    respuesta = await client.post(
        "/api/v1/reclamos/clasificacion",
        json={"titulo": "Fuga de gas", "descripcion": "Sale gas de la vereda, huele muy fuerte"},
        headers=auth(token_ciudadano),
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["prioridad"] == PrioridadReclamo.CRITICA.value

    listado = await client.get("/api/v1/reclamos", headers=auth(token_ciudadano))
    assert listado.json()["total"] == 0


# --- Management --------------------------------------------------------------
async def test_operador_cambia_estado(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    reclamo = await crear_reclamo(client, auth(token_ciudadano))

    respuesta = await client.patch(
        f"/api/v1/reclamos/{reclamo['id']}/estado",
        json={
            "estado": EstadoReclamo.ASIGNADO.value,
            "motivo": "derivado a la cuadrilla",
            "asignado_a": "cuadrilla-3",
        },
        headers=auth(token_operador),
    )
    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == EstadoReclamo.ASIGNADO.value
    assert respuesta.json()["asignado_a"] == "cuadrilla-3"


async def test_transicion_invalida_devuelve_409(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    reclamo = await crear_reclamo(client, auth(token_ciudadano))

    respuesta = await client.patch(
        f"/api/v1/reclamos/{reclamo['id']}/estado",
        json={"estado": EstadoReclamo.CERRADO.value},
        headers=auth(token_operador),
    )
    assert respuesta.status_code == 409
    assert respuesta.json()["type"].endswith("transicion_invalida")


async def test_historial_registra_los_cambios(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    reclamo = await crear_reclamo(client, auth(token_ciudadano))
    await client.patch(
        f"/api/v1/reclamos/{reclamo['id']}/estado",
        json={"estado": EstadoReclamo.EN_REVISION.value},
        headers=auth(token_operador),
    )

    respuesta = await client.get(
        f"/api/v1/reclamos/{reclamo['id']}/historial", headers=auth(token_ciudadano)
    )
    assert [h["estado_nuevo"] for h in respuesta.json()] == [
        EstadoReclamo.RECIBIDO.value,
        EstadoReclamo.EN_REVISION.value,
    ]


# --- Participation -----------------------------------------------------------
async def test_comentar_y_listar_comentarios(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    reclamo = await crear_reclamo(client, auth(token_ciudadano))

    respuesta = await client.post(
        f"/api/v1/reclamos/{reclamo['id']}/comentarios",
        json={"texto": "Ya estamos trabajando en el tema"},
        headers=auth(token_operador),
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["es_oficial"] is True

    listado = await client.get(
        f"/api/v1/reclamos/{reclamo['id']}/comentarios", headers=auth(token_ciudadano)
    )
    assert len(listado.json()) == 1


async def test_adherir_a_un_reclamo_ajeno(
    client: AsyncClient, auth, token_ciudadano, token_otro_ciudadano
) -> None:
    reclamo = await crear_reclamo(client, auth(token_ciudadano))

    respuesta = await client.post(
        f"/api/v1/reclamos/{reclamo['id']}/adhesiones", headers=auth(token_otro_ciudadano)
    )
    assert respuesta.status_code == 201
    assert respuesta.json()["adhesiones_count"] == 1


async def test_el_autor_no_puede_adherir(client: AsyncClient, auth, token_ciudadano) -> None:
    reclamo = await crear_reclamo(client, auth(token_ciudadano))

    respuesta = await client.post(
        f"/api/v1/reclamos/{reclamo['id']}/adhesiones", headers=auth(token_ciudadano)
    )
    assert respuesta.status_code == 422
    assert respuesta.json()["type"].endswith("adhesion_del_autor")


async def test_adhesion_duplicada_devuelve_409(
    client: AsyncClient, auth, token_ciudadano, token_otro_ciudadano
) -> None:
    reclamo = await crear_reclamo(client, auth(token_ciudadano))
    url = f"/api/v1/reclamos/{reclamo['id']}/adhesiones"

    await client.post(url, headers=auth(token_otro_ciudadano))
    respuesta = await client.post(url, headers=auth(token_otro_ciudadano))

    assert respuesta.status_code == 409
