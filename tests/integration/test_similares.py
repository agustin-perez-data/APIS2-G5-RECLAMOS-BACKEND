"""Grouping similar claims: which ones are offered as the same problem (ADR 0007).

The rule these pin down: same category, open, filed in the last 30 days and
within 300 m. Inside that, a claim under 100 m away is offered even when worded
differently; farther away, the text has to match too.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.enums import CategoriaReclamo, EstadoReclamo, PrioridadReclamo
from app.domain.geo import METROS_POR_GRADO_LATITUD
from app.schemas.reclamo import ReclamoCrear
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID, OTRO_CIUDADANO_ID

ALMAGRO = (-34.6037, -58.4201)

CONSULTA = {
    "titulo": "Luminaria apagada en la esquina",
    "descripcion": "La luz de la esquina de Rivadavia y Medrano no anda hace dias",
}


def al_norte(metros: float) -> tuple[float, float]:
    lat, lon = ALMAGRO
    return lat + metros / METROS_POR_GRADO_LATITUD, lon


async def cargar(
    service: ReclamoService,
    *,
    titulo: str,
    descripcion: str,
    metros: float | None = 0,
    categoria: CategoriaReclamo = CategoriaReclamo.ALUMBRADO,
    barrio: str | None = "Almagro",
    ciudadano_id: str = OTRO_CIUDADANO_ID,
):
    lat, lon = al_norte(metros) if metros is not None else (None, None)
    return await service.crear(
        ReclamoCrear(
            titulo=titulo,
            descripcion=descripcion,
            categoria=categoria,
            prioridad=PrioridadReclamo.MEDIA,
            latitud=lat,
            longitud=lon,
            barrio=barrio,
        ),
        ciudadano_id=ciudadano_id,
    )


async def buscar(service: ReclamoService, **overrides):
    lat, lon = ALMAGRO
    pedido = {
        **CONSULTA,
        "categoria": CategoriaReclamo.ALUMBRADO,
        "latitud": lat,
        "longitud": lon,
        "barrio": "Almagro",
        "ciudadano_id": CIUDADANO_ID,
        **overrides,
    }
    return await service.buscar_similares(**pedido)


# --- What counts as the same problem ----------------------------------------
async def test_encuentra_el_mismo_problema_a_metros(service: ReclamoService) -> None:
    existente = await cargar(
        service,
        titulo="Poste de luz apagado",
        descripcion="El foco de la esquina de Rivadavia y Medrano esta apagado desde el lunes",
        metros=50,
    )

    parecidos = await buscar(service)

    assert [p.reclamo.id for p in parecidos] == [existente.id]
    assert parecidos[0].distancia_metros == 50
    assert "luz" in parecidos[0].terminos_en_comun


async def test_redactado_distinto_pero_a_pocos_metros_se_sugiere(
    service: ReclamoService,
) -> None:
    # "lampara quemada" shares no words with "luminaria apagada": proximity
    # is what flags it as the same outage.
    existente = await cargar(
        service,
        titulo="Lampara quemada",
        descripcion="Se quemo la lampara del poste, quedo todo oscuro",
        metros=30,
    )

    parecidos = await buscar(service)

    assert [p.reclamo.id for p in parecidos] == [existente.id]


async def test_el_mas_parecido_va_primero(service: ReclamoService) -> None:
    menos = await cargar(
        service,
        titulo="Lampara quemada",
        descripcion="Se quemo la lampara del poste, quedo todo oscuro",
        metros=60,
    )
    mas = await cargar(
        service,
        titulo="Luminaria apagada en Rivadavia",
        descripcion="La luminaria de la esquina de Rivadavia y Medrano esta apagada",
        metros=60,
    )

    parecidos = await buscar(service)

    assert [p.reclamo.id for p in parecidos] == [mas.id, menos.id]
    assert parecidos[0].puntaje > parecidos[1].puntaje


# --- What is left out ----------------------------------------------------------
async def test_un_reclamo_lejano_no_se_sugiere(service: ReclamoService) -> None:
    await cargar(
        service,
        titulo="Luminaria apagada en la esquina",
        descripcion="La luz de la esquina no anda hace dias",
        metros=2_000,
    )
    assert await buscar(service) == []


async def test_otra_categoria_no_se_sugiere(service: ReclamoService) -> None:
    await cargar(
        service,
        titulo="Bache en la esquina",
        descripcion="Hay un bache enorme en la esquina de Rivadavia y Medrano",
        metros=20,
        categoria=CategoriaReclamo.BACHES,
    )
    assert await buscar(service) == []


async def test_un_reclamo_cerrado_no_se_sugiere(
    service: ReclamoService, session: AsyncSession
) -> None:
    cerrado = await cargar(
        service, titulo=CONSULTA["titulo"], descripcion=CONSULTA["descripcion"], metros=10
    )
    cerrado.estado = EstadoReclamo.CERRADO
    await session.commit()

    assert await buscar(service) == []


async def test_un_reclamo_viejo_no_se_sugiere(
    service: ReclamoService, session: AsyncSession
) -> None:
    viejo = await cargar(
        service, titulo=CONSULTA["titulo"], descripcion=CONSULTA["descripcion"], metros=10
    )
    viejo.created_at = datetime.now(UTC) - timedelta(days=60)
    await session.commit()

    assert await buscar(service) == []


async def test_lejos_y_con_otro_texto_no_se_sugiere(service: ReclamoService) -> None:
    # Within the radius but past 100 m, and nothing in common: not the same.
    await cargar(
        service,
        titulo="Reflector quemado",
        descripcion="Reflector del playon deportivo sin funcionar",
        metros=250,
    )
    assert await buscar(service) == []


# --- Without coordinates --------------------------------------------------------
async def test_sin_coordenadas_se_compara_por_barrio(service: ReclamoService) -> None:
    mismo_barrio = await cargar(
        service,
        titulo="Luminaria apagada",
        descripcion="La luz de la esquina de Rivadavia no anda",
        metros=None,
        barrio="Almagro",
    )
    await cargar(
        service,
        titulo="Luminaria apagada",
        descripcion="La luz de la esquina de Rivadavia no anda",
        metros=None,
        barrio="Palermo",
    )

    parecidos = await buscar(service, latitud=None, longitud=None, barrio="almagro")

    assert [p.reclamo.id for p in parecidos] == [mismo_barrio.id]
    assert parecidos[0].distancia_metros is None


async def test_sin_categoria_la_infiere_el_clasificador(service: ReclamoService) -> None:
    existente = await cargar(
        service,
        titulo="Poste de luz apagado",
        descripcion="El foco de la esquina de Rivadavia y Medrano esta apagado",
        metros=40,
    )

    parecidos = await buscar(service, categoria=None)

    assert [p.reclamo.id for p in parecidos] == [existente.id]


# --- Who is asking ----------------------------------------------------------------
async def test_marca_los_reclamos_propios(service: ReclamoService) -> None:
    await cargar(
        service,
        titulo=CONSULTA["titulo"],
        descripcion=CONSULTA["descripcion"],
        metros=10,
        ciudadano_id=CIUDADANO_ID,
    )

    parecidos = await buscar(service)

    # The front end shows "you already reported this" instead of "join it".
    assert parecidos[0].es_propio is True
    assert parecidos[0].ya_adherido is False


async def test_marca_los_reclamos_a_los_que_ya_se_sumo(service: ReclamoService) -> None:
    existente = await cargar(
        service, titulo=CONSULTA["titulo"], descripcion=CONSULTA["descripcion"], metros=10
    )
    await service.adherir(existente.id, CIUDADANO_ID)

    parecidos = await buscar(service)

    assert parecidos[0].ya_adherido is True
    assert parecidos[0].es_propio is False


async def test_los_similares_de_un_reclamo_no_lo_incluyen_a_el(
    service: ReclamoService,
) -> None:
    original = await cargar(
        service, titulo=CONSULTA["titulo"], descripcion=CONSULTA["descripcion"], metros=0
    )
    duplicado = await cargar(
        service,
        titulo="Poste de luz apagado",
        descripcion="El foco de la esquina de Rivadavia y Medrano esta apagado",
        metros=40,
    )

    parecidos = await service.similares_de(original.id)

    assert [p.reclamo.id for p in parecidos] == [duplicado.id]


# --- HTTP ---------------------------------------------------------------------------
async def test_el_endpoint_devuelve_los_parecidos(
    client: AsyncClient, auth, token_ciudadano, token_otro_ciudadano
) -> None:
    lat, lon = al_norte(50)
    creado = await client.post(
        "/api/v1/reclamos",
        json={
            "titulo": "Poste de luz apagado",
            "descripcion": "El foco de la esquina de Rivadavia y Medrano esta apagado",
            "categoria": "ALUMBRADO",
            "prioridad": "MEDIA",
            "latitud": lat,
            "longitud": lon,
        },
        headers=auth(token_otro_ciudadano),
    )
    assert creado.status_code == 201

    lat, lon = ALMAGRO
    respuesta = await client.post(
        "/api/v1/reclamos/similares",
        json={**CONSULTA, "latitud": lat, "longitud": lon},
        headers=auth(token_ciudadano),
    )

    assert respuesta.status_code == 200
    [parecido] = respuesta.json()
    assert parecido["id"] == creado.json()["id"]
    assert parecido["distancia_metros"] == 50
    assert 0 < parecido["similitud"] <= 1
    assert parecido["es_propio"] is False
    assert parecido["ya_adherido"] is False
    assert parecido["terminos_en_comun"]


async def test_sin_parecidos_devuelve_lista_vacia(
    client: AsyncClient, auth, token_ciudadano
) -> None:
    respuesta = await client.post(
        "/api/v1/reclamos/similares", json=CONSULTA, headers=auth(token_ciudadano)
    )
    assert respuesta.status_code == 200
    assert respuesta.json() == []


async def test_buscar_similares_requiere_login(client: AsyncClient) -> None:
    respuesta = await client.post("/api/v1/reclamos/similares", json=CONSULTA)
    assert respuesta.status_code == 401


async def test_similares_de_un_reclamo_inexistente_da_404(
    client: AsyncClient, auth, token_operador
) -> None:
    respuesta = await client.get(
        "/api/v1/reclamos/00000000-0000-0000-0000-000000000000/similares",
        headers=auth(token_operador),
    )
    assert respuesta.status_code == 404
