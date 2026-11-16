"""Health and metrics endpoints.

The health ones are public on purpose: the orchestrator calls them, not a user.
The metrics one is not: it describes how the service is used.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.api.deps import AdminDep, SessionDep
from app.core import metrics
from app.core.config import settings

router = APIRouter(tags=["health"])

# HEAD as well as GET: uptime monitors and some load balancers probe with HEAD,
# and answering 405 to them reads as "down" while the service is fine.
_SONDEO = ["GET", "HEAD"]


@router.api_route("/health", methods=_SONDEO, summary="Liveness: el proceso esta vivo")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
    }


@router.api_route("/health/ready", methods=_SONDEO, summary="Readiness: hay conexion con la base")
async def ready(session: SessionDep, response: Response) -> dict:
    # Without a database we cannot serve anything useful, so readiness has to
    # fail and let the load balancer pull the instance out of rotation.
    try:
        await session.execute(text("SELECT 1"))
        base = "ok"
    except Exception as exc:  # noqa: BLE001 - the detail is reported to the operator
        base = f"error: {type(exc).__name__}"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if base == "ok" else "degraded",
        "database": base,
        "kafka_enabled": settings.kafka_enabled,
    }


@router.get(
    "/metrics",
    summary="Metricas operativas en formato Prometheus (admin)",
    response_class=Response,
    responses={200: {"content": {"text/plain": {}}}},
)
async def metricas(usuario: AdminDep) -> Response:
    # Administrators only: request volumes per route and event counts say a lot
    # about how the service is used. A scraper would need its own credential;
    # there is none yet, so for now a person reads this.
    return Response(content=metrics.exposicion(), media_type=metrics.TIPO_DE_CONTENIDO)
