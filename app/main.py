"""Entry point of the Claims and Citizen Participation API."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import registrar_manejadores
from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.session import cerrar_engine
from app.events.producer import crear_publisher

log = get_logger(__name__)

CABECERA_CORRELACION = "X-Correlation-Id"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()

    # The producer holds open connections to the broker, so it is created once
    # per process and shared through app.state.
    publisher = crear_publisher()
    await publisher.start()
    app.state.publisher = publisher

    if not settings.auth_enabled:
        log.warning(
            "seguridad.auth_deshabilitada", detalle="AUTH_ENABLED=false, solo para desarrollo"
        )

    log.info(
        "app.iniciada",
        environment=settings.environment,
        kafka=settings.kafka_enabled,
        version=__version__,
    )
    try:
        yield
    finally:
        await publisher.stop()
        await cerrar_engine()
        log.info("app.detenida")


app = FastAPI(
    title="CityPass+ | Reclamos y Participacion Ciudadana",
    description=(
        "Modulo del Grupo 5. Alta, clasificacion automatica y seguimiento de "
        "reclamos vecinales. Publica y consume eventos del bus de CityPass+.\n\n"
        "Todos los endpoints requieren un JWT emitido por el modulo de Login "
        "Federado (Grupo 2)."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[CABECERA_CORRELACION],
)


@app.middleware("http")
async def correlacion_middleware(request: Request, call_next):
    """Propagate (or mint) the correlation id and bind it to every log line.

    This is what makes it possible to follow an operation that starts as an
    HTTP request and continues as events in other modules.
    """
    correlation_id = request.headers.get(CABECERA_CORRELACION) or str(uuid.uuid4())

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        correlation_id=correlation_id,
        path=request.url.path,
        method=request.method,
    )

    respuesta = await call_next(request)
    respuesta.headers[CABECERA_CORRELACION] = correlation_id
    return respuesta


registrar_manejadores(app)
app.include_router(health.router)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def raiz() -> dict:
    return {
        "servicio": settings.app_name,
        "modulo": "Reclamos y Participacion Ciudadana (Grupo 5)",
        "version": __version__,
        "docs": "/docs",
    }
