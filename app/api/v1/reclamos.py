"""REST API of the claims module.

`summary` and `description` stay in Spanish: they are what the other teams read
on the OpenAPI page.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.api.deps import AdminDep, ServiceDep, StaffDep, UsuarioDep
from app.api.visibilidad import comentarios_visibles, historial_visible, reclamo_visible
from app.core.config import settings
from app.core.rate_limit import limiter
from app.domain.enums import CategoriaReclamo, EstadoReclamo, PrioridadReclamo
from app.repositories.reclamo_repository import ORDENES_PERMITIDOS, FiltroReclamos
from app.schemas.common import Page
from app.schemas.reclamo import (
    AdhesionOut,
    BusquedaSimilares,
    CambioEstado,
    CierreAutomaticoOut,
    ClasificacionPedido,
    ComentarioCrear,
    ComentarioOut,
    ConfusionDelModelo,
    ConteoPorClave,
    CorreccionDelModelo,
    DesempenoClasificador,
    Estadisticas,
    HistorialOut,
    ReclamoBandeja,
    ReclamoCrear,
    ReclamoDetalle,
    ReclamoListado,
    ReclamoOut,
    ReclamoResumen,
    ReclamoSimilar,
    ReclasificacionPedido,
    SugerenciaClasificacion,
)
from app.services.clasificador import get_clasificador
from app.services.reclamo_service import ReclamoParecido

router = APIRouter(prefix="/reclamos", tags=["reclamos"])


def _a_similar(parecido: ReclamoParecido) -> ReclamoSimilar:
    return ReclamoSimilar(
        **ReclamoResumen.model_validate(parecido.reclamo).model_dump(),
        similitud=parecido.puntaje,
        distancia_metros=parecido.distancia_metros,
        terminos_en_comun=parecido.terminos_en_comun,
        es_propio=parecido.es_propio,
        ya_adherido=parecido.ya_adherido,
    )


@router.post(
    "",
    response_model=ReclamoOut,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un reclamo",
    description=(
        "Si no se envian `categoria` y `prioridad`, las sugiere el clasificador "
        "automatico. Publica el evento `reclamos.reclamo.creado`."
    ),
)
@limiter.limit(settings.rate_limit_creacion)
async def crear_reclamo(
    request: Request, datos: ReclamoCrear, usuario: UsuarioDep, service: ServiceDep
) -> ReclamoOut:
    reclamo = await service.crear(datos, ciudadano_id=usuario.id)
    return ReclamoOut.model_validate(reclamo)


@router.get("", response_model=Page[ReclamoListado], summary="Listar reclamos")
async def listar_reclamos(
    usuario: UsuarioDep,
    service: ServiceDep,
    estado: EstadoReclamo | None = None,
    categoria: CategoriaReclamo | None = None,
    prioridad: PrioridadReclamo | None = None,
    ciudadano_id: str | None = None,
    asignado_a: str | None = None,
    barrio: str | None = None,
    texto: Annotated[str | None, Query(description="Busqueda en titulo y descripcion")] = None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    orden: Annotated[str, Query(description=f"Uno de: {', '.join(ORDENES_PERMITIDOS)}")] = (
        "recientes"
    ),
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    actividad_id: Annotated[
        uuid.UUID | None,
        Query(description="Solo los relacionados con esta actividad masiva (GET /actividades)"),
    ] = None,
) -> Page[ReclamoListado]:
    filtro = FiltroReclamos(
        estado=estado,
        categoria=categoria,
        prioridad=prioridad,
        ciudadano_id=ciudadano_id,
        asignado_a=asignado_a,
        barrio=barrio,
        texto=texto,
        desde=desde,
        hasta=hasta,
        orden=orden,
        actividad_id=actividad_id,
    )
    items, total = await service.listar(filtro, page=page, size=size)
    return Page[ReclamoListado](
        items=[
            ReclamoListado(
                **ReclamoResumen.model_validate(item).model_dump(),
                es_propio=item.ciudadano_id == usuario.id,
            )
            for item in items
        ],
        total=total,
        page=page,
        size=size,
    )


@router.get(
    "/estadisticas",
    response_model=Estadisticas,
    summary="Metricas agregadas del modulo",
    description=(
        "Alimenta el dashboard propio y el modulo de Analitica Urbana (Grupo 8). "
        "Requiere rol `admin`: un operador gestiona la bandeja pero no accede a "
        "las metricas de gestion."
    ),
)
async def estadisticas(_usuario: AdminDep, service: ServiceDep) -> Estadisticas:
    datos = await service.estadisticas()
    return Estadisticas(
        total=datos["total"],
        por_estado=[ConteoPorClave(clave=k, cantidad=v) for k, v in datos["por_estado"]],
        por_categoria=[ConteoPorClave(clave=k, cantidad=v) for k, v in datos["por_categoria"]],
        por_prioridad=[ConteoPorClave(clave=k, cantidad=v) for k, v in datos["por_prioridad"]],
        tiempo_resolucion_horas_promedio=datos["tiempo_resolucion_horas_promedio"],
        clasificador=DesempenoClasificador(
            clasificados_por_modelo=datos["clasificador"]["clasificados_por_modelo"],
            corregidos_por_operador=datos["clasificador"]["corregidos_por_operador"],
            tasa_de_correccion=datos["clasificador"]["tasa_de_correccion"],
            correcciones=[
                ConfusionDelModelo(sugerida=s, corregida=c, cantidad=n)
                for s, c, n in datos["clasificador"]["correcciones"]
            ],
        ),
    )


@router.get(
    "/clasificador/correcciones",
    summary="Reclamos donde un operador corrigio la categoria del modelo",
    description=(
        "Material para ampliar el corpus del clasificador: los casos que el "
        "modelo clasifico mal, con la etiqueta que les puso quien los corrigio "
        "(ADR 0019). Requiere rol `admin`. Los mas recientes primero."
    ),
)
async def correcciones_del_modelo(
    _usuario: AdminDep,
    service: ServiceDep,
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[CorreccionDelModelo]:
    reclamos = await service.correcciones_del_modelo(limite)
    return [CorreccionDelModelo.model_validate(reclamo) for reclamo in reclamos]


@router.post(
    "/mantenimiento/cierre-automatico",
    summary="Cerrar los reclamos resueltos cuyo plazo de respuesta vencio",
    description=(
        "Pasa a `CERRADO` los reclamos que llevan mas de `DIAS_CIERRE_AUTOMATICO` "
        "dias en `RESUELTO` sin respuesta del vecino (US-17). Cada cierre deja su "
        "entrada en el historial, avisa al vecino y publica el cambio de estado. "
        "Es idempotente: una segunda llamada no encuentra nada que cerrar. "
        "Requiere rol `admin`. La API ya lo hace sola cada hora (ADR 0025); "
        "este endpoint queda para dispararlo a mano."
    ),
)
async def cierre_automatico(_usuario: AdminDep, service: ServiceDep) -> CierreAutomaticoOut:
    cerrados = await service.cerrar_resueltos_vencidos()
    return CierreAutomaticoOut(cerrados=len(cerrados), reclamo_ids=[r.id for r in cerrados])


@router.post(
    "/clasificacion",
    response_model=SugerenciaClasificacion,
    summary="Sugerir categoria y prioridad sin persistir nada",
    description=(
        "Permite que la app muestre la sugerencia mientras el vecino escribe, y "
        "que el operador audite que decidiria el modelo."
    ),
)
async def sugerir_clasificacion(
    pedido: ClasificacionPedido, _usuario: UsuarioDep
) -> SugerenciaClasificacion:
    return get_clasificador().clasificar(pedido.titulo, pedido.descripcion)


@router.post(
    "/similares",
    response_model=list[ReclamoSimilar],
    summary="Buscar reclamos parecidos antes de cargar uno nuevo",
    description=(
        "Recibe el reclamo que el vecino esta escribiendo, sin guardarlo, y devuelve "
        f"hasta {settings.similares_maximo} reclamos abiertos que probablemente sean el "
        "mismo problema: misma categoria, cargados en los ultimos "
        f"{settings.similares_ventana_dias} dias y a menos de "
        f"{settings.similares_radio_metros} m. Se ordenan por similitud de texto y "
        "cercania. Si hay alguno, la app puede ofrecerle sumarse "
        "(`POST /reclamos/{id}/adhesiones`) en lugar de crear un duplicado. Lista "
        "vacia si no hay ninguno parecido."
    ),
)
async def buscar_similares(
    pedido: BusquedaSimilares, usuario: UsuarioDep, service: ServiceDep
) -> list[ReclamoSimilar]:
    parecidos = await service.buscar_similares(
        titulo=pedido.titulo,
        descripcion=pedido.descripcion,
        categoria=pedido.categoria,
        latitud=pedido.latitud,
        longitud=pedido.longitud,
        barrio=pedido.barrio,
        ciudadano_id=usuario.id,
    )
    return [_a_similar(p) for p in parecidos]


@router.get(
    "/bandeja",
    response_model=Page[ReclamoBandeja],
    summary="Bandeja de reclamos entrantes",
    description="bandeja de reclamos que ve el gestor municipal",
)
async def bandeja_reclamos(
    _gestor: StaffDep,
    service: ServiceDep,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[ReclamoBandeja]:
    filtro = FiltroReclamos(
        estados=[EstadoReclamo.RECIBIDO, EstadoReclamo.EN_REVISION],
        orden="recientes",
    )
    items, total = await service.listar(filtro, page=page, size=size)
    return Page[ReclamoBandeja](
        items=[ReclamoBandeja.model_validate(i) for i in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/{reclamo_id}", response_model=ReclamoDetalle, summary="Detalle de un reclamo")
async def obtener_reclamo(
    reclamo_id: uuid.UUID, usuario: UsuarioDep, service: ServiceDep
) -> ReclamoDetalle:
    reclamo = await service.obtener(reclamo_id)
    # Any authenticated user may read a claim, but not its internal side.
    return reclamo_visible(ReclamoDetalle.model_validate(reclamo), usuario)


@router.patch(
    "/{reclamo_id}/estado",
    response_model=ReclamoOut,
    summary="Cambiar el estado de un reclamo (operador/admin)",
    description=(
        "Valida la maquina de estados y publica `reclamos.reclamo.estado-cambiado` "
        "(y `reclamos.reclamo.resuelto` al resolver)."
    ),
)
async def cambiar_estado(
    reclamo_id: uuid.UUID, cambio: CambioEstado, actor: StaffDep, service: ServiceDep
) -> ReclamoOut:
    reclamo = await service.cambiar_estado(reclamo_id, cambio, actor)
    return ReclamoOut.model_validate(reclamo)


@router.patch(
    "/{reclamo_id}/clasificacion",
    response_model=ReclamoOut,
    summary="Corregir la clasificacion de un reclamo (operador/admin)",
    description=(
        "Corrige categoria, prioridad y/o objeto afectado, para cuando el modelo "
        "o el ciudadano clasificaron mal. No cambia el estado del reclamo; "
        "publica `reclamos.reclamo.clasificado` de nuevo."
    ),
)
async def reclasificar(
    reclamo_id: uuid.UUID, cambio: ReclasificacionPedido, actor: StaffDep, service: ServiceDep
) -> ReclamoOut:
    reclamo = await service.reclasificar(reclamo_id, cambio, actor)
    return ReclamoOut.model_validate(reclamo)


@router.post(
    "/{reclamo_id}/comentarios",
    response_model=ComentarioOut,
    status_code=status.HTTP_201_CREATED,
    summary="Comentar un reclamo",
)
@limiter.limit(settings.rate_limit_comentarios)
async def comentar(
    request: Request,
    reclamo_id: uuid.UUID,
    datos: ComentarioCrear,
    usuario: UsuarioDep,
    service: ServiceDep,
) -> ComentarioOut:
    comentario = await service.comentar(reclamo_id, datos.texto, usuario)
    return ComentarioOut.model_validate(comentario)


@router.get(
    "/{reclamo_id}/comentarios",
    response_model=list[ComentarioOut],
    summary="Comentarios de un reclamo",
)
async def listar_comentarios(
    reclamo_id: uuid.UUID, usuario: UsuarioDep, service: ServiceDep
) -> list[ComentarioOut]:
    await service.obtener(reclamo_id)  # raises 404 when it does not exist
    comentarios = await service.repo.comentarios_de(reclamo_id)
    return comentarios_visibles([ComentarioOut.model_validate(c) for c in comentarios], usuario)


@router.get(
    "/{reclamo_id}/historial",
    response_model=list[HistorialOut],
    summary="Trazabilidad de estados del reclamo",
)
async def listar_historial(
    reclamo_id: uuid.UUID, usuario: UsuarioDep, service: ServiceDep
) -> list[HistorialOut]:
    reclamo = await service.obtener(reclamo_id)
    historial = await service.repo.historial_de(reclamo_id)
    return historial_visible(
        [HistorialOut.model_validate(h) for h in historial], usuario, reclamo.ciudadano_id
    )


@router.get(
    "/{reclamo_id}/similares",
    response_model=list[ReclamoSimilar],
    summary="Posibles duplicados de un reclamo",
    description=(
        "Otros reclamos abiertos que probablemente sean el mismo problema, con los "
        "mismos criterios que `POST /reclamos/similares`. Le ahorra al operador "
        "revisar la bandeja entera para encontrar duplicados."
    ),
)
async def similares_de(
    reclamo_id: uuid.UUID, usuario: UsuarioDep, service: ServiceDep
) -> list[ReclamoSimilar]:
    parecidos = await service.similares_de(reclamo_id, ciudadano_id=usuario.id)
    return [_a_similar(p) for p in parecidos]


@router.post(
    "/{reclamo_id}/adhesiones",
    response_model=AdhesionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Adherir a un reclamo existente",
    description=(
        "'A mi tambien me pasa'. Al alcanzar el umbral configurado el reclamo "
        "escala de prioridad automaticamente."
    ),
)
@limiter.limit(settings.rate_limit_adhesiones)
async def adherir(
    request: Request, reclamo_id: uuid.UUID, usuario: UsuarioDep, service: ServiceDep
) -> AdhesionOut:
    reclamo = await service.adherir(reclamo_id, usuario.id)
    return AdhesionOut(
        reclamo_id=reclamo.id,
        adhesiones_count=reclamo.adhesiones_count,
        prioridad=reclamo.prioridad,
    )
