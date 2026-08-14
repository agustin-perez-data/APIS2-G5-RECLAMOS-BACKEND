"""Health endpoints. Public on purpose: the orchestrator calls them, not a user."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app import __version__
from app.api.deps import SessionDep
from app.core.config import settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness: el proceso esta vivo")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": __version__,
        "environment": settings.environment,
    }


@router.get("/health/ready", summary="Readiness: hay conexion con la base")
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
