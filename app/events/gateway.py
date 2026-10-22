"""Publication through the CityPass+ event gateway (Group 1) - CU-INT-01.

The gateway takes plain JSON over HTTP, validates it against the Avro schema
registered for the event type and adds the metadata itself (eventId, source,
receivedAt). So this publisher translates our internal envelope into the
gateway's event types, whose names and fields are the cross-team contract
(`docs/cu-int-01/event-types.json` in the gateway repo):

    reclamos.reclamo.creado          -> com.citypass.reclamos.ReclamoCreado
    reclamos.reclamo.estado-cambiado -> com.citypass.reclamos.ReclamoActualizado

Every other internal event (classified, resolved, commented...) has no
consumer outside the module, so it is not sent. "Resolved" travels inside
ReclamoActualizado with estadoNuevo=RESUELTO.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import httpx

from app.core.config import Settings, settings
from app.core.logging import get_logger
from app.domain.enums import CATEGORIAS_QUE_AFECTAN_CIRCULACION, CategoriaReclamo
from app.events import topics
from app.events.contracts import EventEnvelope, ReclamoCreado, ReclamoEstadoCambiado
from app.events.producer import EventPublisher

log = get_logger(__name__)

# Retries inside the request. The claim is already committed when we publish,
# so after the last attempt the failure is logged, never raised: the citizen
# must not get a 500 for a claim that was actually filed.
_REINTENTOS = 3
_ESPERA_BASE_SEGUNDOS = 0.5


def _epoch_ms(momento: datetime) -> int:
    return int(momento.timestamp() * 1000)


def traducir(topic: str, envelope: EventEnvelope) -> tuple[str, dict[str, Any]] | None:
    """Internal event -> (gateway event name, business fields). None = not published."""
    data = envelope.data

    if topic == topics.RECLAMO_CREADO and isinstance(data, ReclamoCreado):
        return "ReclamoCreado", {
            "reclamoId": str(data.reclamo_id),
            "ciudadanoId": data.ciudadano_id,
            "canal": data.canal or "APP",
            "titulo": data.titulo,
            "descripcion": data.descripcion or data.titulo,
            "categoria": str(data.categoria),
            "prioridad": str(data.prioridad),
            "origenClasificacion": data.origen_clasificacion or "CIUDADANO",
            "confianzaClasificacion": data.confianza_clasificacion,
            "direccion": data.direccion,
            "barrio": data.barrio,
            "latitud": data.latitud,
            "longitud": data.longitud,
            "afectaCirculacion": CategoriaReclamo(data.categoria)
            in CATEGORIAS_QUE_AFECTAN_CIRCULACION,
            "correlationId": envelope.correlation_id,
            "createdAt": _epoch_ms(data.creado_at),
        }

    if topic == topics.RECLAMO_ESTADO_CAMBIADO and isinstance(data, ReclamoEstadoCambiado):
        return "ReclamoActualizado", {
            "reclamoId": str(data.reclamo_id),
            "ciudadanoId": data.ciudadano_id,
            "estadoNuevo": str(data.estado_nuevo),
            "estadoAnterior": str(data.estado_anterior),
            "motivo": data.motivo,
            "asignadoA": data.asignado_a,
            "cambiadoPor": data.cambiado_por,
            "correlationId": envelope.correlation_id,
            "updatedAt": _epoch_ms(data.cambiado_at),
        }

    return None


class GatewayEventPublisher(EventPublisher):
    """Publishes through the gateway with a cached client_credentials token."""

    def __init__(
        self, cfg: Settings | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._cfg = cfg or settings
        self._client = client
        self._token: str | None = None
        self._token_vence = 0.0

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._cfg.gateway_timeout_seconds)
        log.info("publisher.gateway.start", url=self._cfg.gateway_url)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            log.info("publisher.gateway.stop")

    async def _enviar(self, topic: str, key: str | None, envelope: EventEnvelope) -> None:
        traduccion = traducir(topic, envelope)
        if traduccion is None:
            log.debug("evento.no_publicado_en_gateway", topic=topic)
            return

        nombre, datos = traduccion
        fqn = f"{self._cfg.gateway_namespace}.{nombre}"
        for intento in range(1, _REINTENTOS + 1):
            try:
                await self._post(fqn, datos)
                log.info(
                    "evento.publicado.gateway", tipo=fqn, key=key, event_id=str(envelope.event_id)
                )
                return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (400, 404):
                    # Contract violation or unknown type: retrying gives the same answer.
                    log.error("evento.rechazado.gateway", tipo=fqn, detalle=exc.response.text)
                    return
                if exc.response.status_code == 401:
                    self._token = None
                error = f"HTTP {exc.response.status_code}"
            except httpx.HTTPError as exc:
                error = repr(exc)

            if intento < _REINTENTOS:
                await asyncio.sleep(_ESPERA_BASE_SEGUNDOS * 2 ** (intento - 1))

        log.error("evento.no_publicado.gateway", tipo=fqn, key=key, error=error)

    async def _post(self, fqn: str, datos: dict[str, Any]) -> None:
        if self._client is None:
            raise RuntimeError("El publisher del gateway no fue inicializado (falta start())")
        token = await self._obtener_token()
        respuesta = await self._client.post(
            f"{self._cfg.gateway_url}/api/v1/event-types/{fqn}/events",
            json=datos,
            headers={"Authorization": f"Bearer {token}"},
        )
        respuesta.raise_for_status()

    async def _obtener_token(self) -> str:
        # Reused until 30 s before expiry: tokens last 15 minutes.
        if self._token and time.monotonic() < self._token_vence - 30:
            return self._token
        assert self._client is not None
        respuesta = await self._client.post(
            self._cfg.gateway_token_url,
            data={"grant_type": "client_credentials"},
            auth=(self._cfg.gateway_client_id, self._cfg.gateway_client_secret),
        )
        respuesta.raise_for_status()
        cuerpo = respuesta.json()
        self._token = cuerpo["access_token"]
        self._token_vence = time.monotonic() + float(cuerpo.get("expires_in", 900))
        return self._token
