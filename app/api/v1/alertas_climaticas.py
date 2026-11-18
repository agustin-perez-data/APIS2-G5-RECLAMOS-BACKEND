"""Weather alerts, as the municipal staff sees them (ADR 0014)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ServiceDep, StaffDep
from app.schemas.alerta_climatica import AlertaClimaticaOut

router = APIRouter(prefix="/alertas-climaticas", tags=["Alertas climaticas"])


@router.get(
    "/activas",
    response_model=list[AlertaClimaticaOut],
    summary="Alertas climaticas en vigencia",
    description=(
        "Las alertas que rigen en este momento: confirmadas por Espacios Publicos, "
        "con la vigencia ya iniciada, sin vencer y sin finalizar. Una alerta "
        "anunciada para mas tarde no figura hasta que empieza, y una cuya vigencia "
        "termino tampoco, aunque no haya llegado su cierre. De la mas reciente a la "
        "mas antigua. Requiere rol `operador` o `admin`."
    ),
)
async def alertas_activas(_usuario: StaffDep, service: ServiceDep) -> list[AlertaClimaticaOut]:
    return [AlertaClimaticaOut.model_validate(alerta) for alerta in await service.clima.vigentes()]
