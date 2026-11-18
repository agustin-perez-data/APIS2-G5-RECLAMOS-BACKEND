"""Operational metrics, in the Prometheus exposition format.

Logs answer "what happened to this request"; these answer "how is the service
doing": how many requests fail, how slow they are, and whether events are
reaching the bus. They are the numbers an alert or a dashboard is built on.

Kept in memory, per process. That is exact with the single instance the
service runs on and resets on every deploy, which is how counters are meant to
be read (as rates), not a defect.

Labels are closed sets on purpose: the route *template*, never the URL, and the
event type, never an id. A label with unbounded values grows the registry
without limit.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    Info,
    generate_latest,
)

from app import __version__
from app.core.config import settings

# Requests that match no route share one label, so a scanner probing random
# URLs cannot create one series per URL.
RUTA_DESCONOCIDA = "sin_ruta"

INFO = Info("reclamos_build", "Version desplegada y entorno")
INFO.info({"version": __version__, "environment": settings.environment})

PEDIDOS = Counter(
    "reclamos_http_requests_total",
    "Pedidos HTTP atendidos, por metodo, plantilla de ruta y status",
    ["method", "route", "status"],
)

DURACION = Histogram(
    "reclamos_http_request_duration_seconds",
    "Duracion de los pedidos HTTP, por metodo y plantilla de ruta",
    ["method", "route"],
    # Up to 30 s: a cold start or a slow Jira call is exactly what must show.
    buckets=(0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

# resultado: publicado | rechazado (the gateway refused the contract) |
# fallido (retries exhausted: the event did not leave)
EVENTOS_PUBLICADOS = Counter(
    "reclamos_eventos_publicados_total",
    "Eventos enviados al gateway de CityPass+, por tipo y resultado",
    ["tipo", "resultado"],
)

# resultado: procesado | ignorado (a type we do not handle) | error (the
# handler failed and the gateway will retry)
EVENTOS_RECIBIDOS = Counter(
    "reclamos_eventos_recibidos_total",
    "Eventos de otros modulos recibidos por webhook, por topico y resultado",
    ["topic", "resultado"],
)

# The same events, read straight from the bus' Kafka (ADR 0023). A counter of
# its own so the two roads can be told apart while both are open.
# resultado: procesado | ignorado (a type we do not handle) | ilegible (does
# not decode) | invalido (decodes, but breaks the contract) | error (the
# handler kept failing and the event was skipped)
EVENTOS_DEL_BUS = Counter(
    "reclamos_eventos_bus_total",
    "Eventos de otros modulos leidos del Kafka del bus, por topico y resultado",
    ["topic", "resultado"],
)

# 1 while the consumer holds a connection to the bus' broker. With the flag
# on, a 0 that lasts means events are not being read.
BUS_CONECTADO = Gauge(
    "reclamos_bus_conectado",
    "1 si el consumidor del Kafka del bus esta conectado, 0 si no",
)

TIPO_DE_CONTENIDO = CONTENT_TYPE_LATEST


def plantilla_de_ruta(scope: dict[str, Any]) -> str:
    """The route template of a request: `/api/v1/reclamos/{reclamo_id}`.

    The router leaves the matched route in the scope, but a route declared in
    an included router only knows its own part (`/reclamos/{reclamo_id}`), not
    the prefix it was mounted under. The prefix is read off the real path: the
    route's part is its tail, so whatever comes before it is the prefix. Two
    routers with the same sub-path stay apart that way.
    """
    parte = getattr(scope.get("route"), "path", None)
    if not parte:
        return RUTA_DESCONOCIDA
    segmentos = [s for s in parte.split("/") if s]
    pedido = [s for s in str(scope.get("path", "")).split("/") if s]
    prefijo = pedido[: max(len(pedido) - len(segmentos), 0)]
    return "/" + "/".join(prefijo + segmentos)


def exposicion() -> bytes:
    """Every metric of the process, ready to be scraped."""
    return generate_latest()
