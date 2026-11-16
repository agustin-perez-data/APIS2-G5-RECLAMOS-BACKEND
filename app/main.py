"""Entry point of the Claims and Citizen Participation API."""

from __future__ import annotations

import asyncio
import contextlib
import time
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
from app.core.metrics import DURACION, PEDIDOS, plantilla_de_ruta
from app.core.rate_limit import limiter
from app.db.session import cerrar_engine
from app.events.producer import crear_publisher

log = get_logger(__name__)

CABECERA_CORRELACION = "X-Correlation-Id"

# Anything else is counted under one label: the method is sent by the client,
# and a metric label must not take arbitrary values.
METODOS_HTTP = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})


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

    # The bus consumer shares the process (ADR 0023): a worker of its own is a
    # second paid service. It reconnects by itself and never raises, so a broker
    # that is down costs events arriving late, not the API.
    tarea_bus: asyncio.Task[None] | None = None
    if settings.bus_kafka_enabled:
        from app.events.bus import BusConsumer

        tarea_bus = asyncio.create_task(BusConsumer(publisher).run(), name="bus-citypass")

    log.info(
        "app.iniciada",
        environment=settings.environment,
        kafka=settings.kafka_enabled,
        bus_kafka=settings.bus_kafka_enabled,
        version=__version__,
    )
    try:
        yield
    finally:
        if tarea_bus is not None:
            tarea_bus.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await tarea_bus
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

# SlowAPI requires the limiter to be stored in app.state so its decorators
# can resolve it at request time.
app.state.limiter = limiter

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
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


@app.middleware("http")
async def metricas_middleware(request: Request, call_next):
    """Count and time every request, by method, route template and status."""
    inicio = time.perf_counter()
    estado = 500  # what the client gets when something below raises
    try:
        respuesta = await call_next(request)
        estado = respuesta.status_code
        return respuesta
    finally:
        # The template ("/api/v1/reclamos/{reclamo_id}") is the label, never
        # the URL: one series per route, not one per claim.
        ruta = plantilla_de_ruta(request.scope)
        metodo = request.method if request.method in METODOS_HTTP else "OTRO"
        PEDIDOS.labels(metodo, ruta, str(estado)).inc()
        DURACION.labels(metodo, ruta).observe(time.perf_counter() - inicio)


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
