"""Mass activities announced by Public Spaces (squad 3, ADR 0013).

Read-only: activities only arrive through `com.citypass.espacios.ActividadCreada`.
`summary` and `description` stay in Spanish: they are what the other teams read
on the OpenAPI page.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.api.deps import ServiceDep, StaffDep
from app.core.config import settings
from app.schemas.actividad import ActividadOut

router = APIRouter(prefix="/actividades", tags=["actividades"])


@router.get(
    "",
    response_model=list[ActividadOut],
    summary="Actividades masivas y sus reclamos relacionados (operador/admin)",
    description=(
        "Las actividades de Espacios Publicos de "
        f"{settings.actividad_masiva_capacidad_minima} personas o mas. Todo reclamo que se "
        f"carga a {settings.actividad_masiva_radio_metros} m o menos, desde que empieza la "
        f"actividad hasta {settings.actividad_masiva_horas_despues} h despues de que termina, "
        "queda relacionado con ella. Por defecto solo trae las que todavia relacionan "
        "reclamos o estan por empezar; ordenadas por fecha de inicio. Para ver los reclamos "
        "de una: `GET /reclamos?actividad_id={id}`."
    ),
)
async def listar_actividades(
    _gestor: StaffDep,
    service: ServiceDep,
    incluir_finalizadas: bool = Query(
        default=False, description="Traer tambien las que ya cerraron su ventana"
    ),
) -> list[ActividadOut]:
    filas = await service.actividades.listar(incluir_finalizadas=incluir_finalizadas)
    return [
        ActividadOut.model_validate(actividad).model_copy(
            update={"reclamos_relacionados": cantidad}
        )
        for actividad, cantidad in filas
    ]
