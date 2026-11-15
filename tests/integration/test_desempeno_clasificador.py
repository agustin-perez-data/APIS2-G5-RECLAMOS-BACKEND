"""Measuring the classifier on real claims (ADR 0019).

The model's original suggestion has to survive a reclassification: that is the
only way to know afterwards that the model was wrong.
"""

from __future__ import annotations

from httpx import AsyncClient

from app.domain.enums import CategoriaReclamo, EstadoReclamo, OrigenClasificacion, PrioridadReclamo
from app.schemas.reclamo import ReclamoCrear, ReclasificacionPedido
from app.services.clasificador import ClasificadorNaiveBayes
from app.services.reclamo_service import ReclamoService
from tests.conftest import CIUDADANO_ID

LUMINARIA = {
    "titulo": "Luminaria apagada en la plaza",
    "descripcion": "El foco del poste no enciende hace dos semanas y quedo todo oscuro",
}
BACHE = {
    "titulo": "Pozo profundo en la calzada",
    "descripcion": "Hay un bache enorme en el asfalto que rompe las cubiertas de los autos",
}


# --- What gets stored at filing ----------------------------------------------


async def test_el_alta_guarda_lo_que_sugirio_el_modelo(service: ReclamoService) -> None:
    reclamo = await service.crear(ReclamoCrear(**LUMINARIA), CIUDADANO_ID)

    assert reclamo.categoria_sugerida == "ALUMBRADO"
    assert reclamo.confianza_sugerida == reclamo.confianza_clasificacion
    assert reclamo.modelo_clasificador == ClasificadorNaiveBayes.nombre


async def test_si_el_vecino_elige_la_categoria_no_hay_sugerencia_que_guardar(
    service: ReclamoService,
) -> None:
    reclamo = await service.crear(
        ReclamoCrear(**LUMINARIA, categoria=CategoriaReclamo.ALUMBRADO), CIUDADANO_ID
    )

    assert reclamo.categoria_sugerida is None
    assert reclamo.confianza_sugerida is None
    assert reclamo.modelo_clasificador is None


async def test_elegir_la_categoria_y_no_la_prioridad_no_cuenta_como_modelo(
    service: ReclamoService, publisher
) -> None:
    # The priority still comes from the urgency rule, but the category is the
    # neighbour's: the origin describes who decided the category.
    reclamo = await service.crear(
        ReclamoCrear(**BACHE, categoria=CategoriaReclamo.TRANSITO), CIUDADANO_ID
    )

    assert reclamo.categoria is CategoriaReclamo.TRANSITO
    assert reclamo.origen_clasificacion is OrigenClasificacion.CIUDADANO
    assert reclamo.confianza_clasificacion is None
    assert reclamo.prioridad is not None
    assert "reclamos.reclamo.clasificado" not in publisher.topics


async def test_con_categoria_elegida_la_duda_del_modelo_no_manda_a_revision(
    session, publisher
) -> None:
    from app.core.config import settings

    exigente = settings.model_copy(update={"confianza_minima_clasificador": 1.1})
    service = ReclamoService(session, publisher, cfg=exigente)

    reclamo = await service.crear(
        ReclamoCrear(**BACHE, categoria=CategoriaReclamo.BACHES), CIUDADANO_ID
    )

    # The model's category is not used here, so its confidence must not decide.
    assert reclamo.estado is EstadoReclamo.RECIBIDO


async def test_elegir_solo_la_prioridad_deja_la_categoria_al_modelo(
    service: ReclamoService,
) -> None:
    reclamo = await service.crear(
        ReclamoCrear(**BACHE, prioridad=PrioridadReclamo.BAJA), CIUDADANO_ID
    )

    assert reclamo.origen_clasificacion is OrigenClasificacion.MODELO
    assert reclamo.categoria_sugerida == "BACHES"
    assert reclamo.prioridad is PrioridadReclamo.BAJA


# --- What survives a reclassification ----------------------------------------


async def test_la_sugerencia_sobrevive_a_la_reclasificacion(
    service: ReclamoService, usuario_operador
) -> None:
    reclamo = await service.crear(ReclamoCrear(**LUMINARIA), CIUDADANO_ID)
    confianza = reclamo.confianza_sugerida

    corregido = await service.reclasificar(
        reclamo.id,
        ReclasificacionPedido(categoria=CategoriaReclamo.ESPACIOS_PUBLICOS),
        usuario_operador,
    )

    assert corregido.categoria is CategoriaReclamo.ESPACIOS_PUBLICOS
    assert corregido.confianza_clasificacion is None  # overwritten, as before
    assert corregido.categoria_sugerida == "ALUMBRADO"
    assert corregido.confianza_sugerida == confianza


# --- The metric --------------------------------------------------------------


async def test_sin_reclamos_la_tasa_no_existe(service: ReclamoService) -> None:
    datos = (await service.estadisticas())["clasificador"]

    assert datos == {
        "clasificados_por_modelo": 0,
        "corregidos_por_operador": 0,
        "tasa_de_correccion": None,
        "correcciones": [],
    }


async def test_la_tasa_cuenta_solo_las_correcciones_de_categoria(
    service: ReclamoService, usuario_operador
) -> None:
    corregido = await service.crear(ReclamoCrear(**LUMINARIA), CIUDADANO_ID)
    solo_prioridad = await service.crear(ReclamoCrear(**BACHE), CIUDADANO_ID)
    await service.crear(ReclamoCrear(**LUMINARIA), CIUDADANO_ID)  # never reviewed
    # Chosen by the neighbour: not the model's, so it stays out of the count.
    del_vecino = await service.crear(
        ReclamoCrear(**BACHE, categoria=CategoriaReclamo.BACHES), CIUDADANO_ID
    )

    await service.reclasificar(
        corregido.id,
        ReclasificacionPedido(categoria=CategoriaReclamo.ESPACIOS_PUBLICOS),
        usuario_operador,
    )
    # The operator agreed with the category and only raised the priority.
    await service.reclasificar(
        solo_prioridad.id,
        ReclasificacionPedido(prioridad=PrioridadReclamo.CRITICA),
        usuario_operador,
    )
    await service.reclasificar(
        del_vecino.id, ReclasificacionPedido(categoria=CategoriaReclamo.TRANSITO), usuario_operador
    )

    datos = (await service.estadisticas())["clasificador"]

    assert datos["clasificados_por_modelo"] == 3
    assert datos["corregidos_por_operador"] == 1
    assert datos["tasa_de_correccion"] == round(1 / 3, 4)
    assert datos["correcciones"] == [("ALUMBRADO", "ESPACIOS_PUBLICOS", 1)]


async def test_las_correcciones_traen_el_texto_y_las_dos_etiquetas(
    service: ReclamoService, usuario_operador
) -> None:
    reclamo = await service.crear(ReclamoCrear(**LUMINARIA), CIUDADANO_ID)
    await service.crear(ReclamoCrear(**BACHE), CIUDADANO_ID)  # not corrected
    await service.reclasificar(
        reclamo.id,
        ReclasificacionPedido(categoria=CategoriaReclamo.ESPACIOS_PUBLICOS),
        usuario_operador,
    )

    (correccion,) = await service.correcciones_del_modelo()

    assert correccion.titulo == LUMINARIA["titulo"]
    assert correccion.categoria_sugerida == "ALUMBRADO"
    assert correccion.categoria is CategoriaReclamo.ESPACIOS_PUBLICOS


# --- Through the API ---------------------------------------------------------


async def _alta_y_correccion(client: AsyncClient, auth, token_ciudadano, token_operador) -> str:
    alta = await client.post("/api/v1/reclamos", json=LUMINARIA, headers=auth(token_ciudadano))
    assert alta.status_code == 201
    reclamo_id = alta.json()["id"]
    correccion = await client.patch(
        f"/api/v1/reclamos/{reclamo_id}/clasificacion",
        json={"categoria": "ESPACIOS_PUBLICOS"},
        headers=auth(token_operador),
    )
    assert correccion.status_code == 200
    return reclamo_id


async def test_las_estadisticas_exponen_el_desempeno_del_modelo(
    client: AsyncClient, auth, token_ciudadano, token_operador, token_admin
) -> None:
    await _alta_y_correccion(client, auth, token_ciudadano, token_operador)

    respuesta = await client.get("/api/v1/reclamos/estadisticas", headers=auth(token_admin))

    assert respuesta.status_code == 200
    assert respuesta.json()["clasificador"] == {
        "clasificados_por_modelo": 1,
        "corregidos_por_operador": 1,
        "tasa_de_correccion": 1.0,
        "correcciones": [
            {"sugerida": "ALUMBRADO", "corregida": "ESPACIOS_PUBLICOS", "cantidad": 1}
        ],
    }


async def test_el_admin_baja_las_correcciones_para_el_corpus(
    client: AsyncClient, auth, token_ciudadano, token_operador, token_admin
) -> None:
    reclamo_id = await _alta_y_correccion(client, auth, token_ciudadano, token_operador)

    respuesta = await client.get(
        "/api/v1/reclamos/clasificador/correcciones", headers=auth(token_admin)
    )

    assert respuesta.status_code == 200
    (fila,) = respuesta.json()
    assert fila["id"] == reclamo_id
    assert fila["titulo"] == LUMINARIA["titulo"]
    assert fila["descripcion"] == LUMINARIA["descripcion"]
    assert fila["categoria_sugerida"] == "ALUMBRADO"
    assert fila["categoria"] == "ESPACIOS_PUBLICOS"
    assert fila["modelo_clasificador"] == ClasificadorNaiveBayes.nombre


async def test_las_correcciones_son_solo_para_admin(
    client: AsyncClient, auth, token_ciudadano, token_operador
) -> None:
    ruta = "/api/v1/reclamos/clasificador/correcciones"

    assert (await client.get(ruta)).status_code == 401
    assert (await client.get(ruta, headers=auth(token_ciudadano))).status_code == 403
    assert (await client.get(ruta, headers=auth(token_operador))).status_code == 403


async def test_el_limite_de_correcciones_se_valida(client: AsyncClient, auth, token_admin) -> None:
    respuesta = await client.get(
        "/api/v1/reclamos/clasificador/correcciones?limite=0", headers=auth(token_admin)
    )

    assert respuesta.status_code == 422
