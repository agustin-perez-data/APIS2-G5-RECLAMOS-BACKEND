"""Webhook for events delivered by the CityPass+ gateway (CU-INT-01).

The gateway's dispatcher POSTs every event of a subscribed type here, with its
own envelope: `{"metadata": {eventId, eventType, source, receivedAt}, "data": {...}}`.
This endpoint translates it into our internal envelope and runs the same
handlers the Kafka worker uses, so an event behaves the same whatever road it
arrives by.

Authentication: the dispatcher does not sign deliveries nor send a JWT, so a
shared secret travels with each delivery, compared in constant time. It is read
from the `X-Webhook-Token` header when the subscription can send headers, and
from `?token=...` otherwise - the query parameter ends up in the access log, so
`app.core.logging` masks it.
Delivery is at-least-once; the handlers are idempotent (see handlers.py).
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_publisher
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import EVENTOS_RECIBIDOS
from app.core.rate_limit import limiter
from app.db.session import get_session
from app.events.entrada import a_sobre_interno
from app.events.handlers import HANDLERS
from app.events.producer import EventPublisher
from app.services.reclamo_service import ReclamoService

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Integracion CityPass+"])


def _token_valido(token: str | None) -> bool:
    esperado = settings.gateway_webhook_token
    if not esperado or not token:
        return False
    return hmac.compare_digest(esperado.encode(), token.encode())


@router.post(
    "/citypass",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Recibe un evento del gateway de CityPass+",
    responses={401: {"description": "Token invalido"}, 400: {"description": "Evento mal formado"}},
)
@limiter.limit(settings.rate_limit_webhook)
async def recibir_evento(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    publisher: Annotated[EventPublisher, Depends(get_publisher)],
    token: str | None = Query(default=None),
    token_cabecera: Annotated[str | None, Header(alias="X-Webhook-Token")] = None,
) -> Response:
    if not _token_valido(token_cabecera or token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")

    try:
        sobre = await request.json()
        traducido = a_sobre_interno(sobre)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if traducido is None:
        # No topic label: the type comes from outside and is not a closed set.
        EVENTOS_RECIBIDOS.labels("otro", "ignorado").inc()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    topic, interno = traducido
    # A failure here returns 500: the dispatcher retries and, after three
    # attempts, leaves the event in its dead letter queue.
    try:
        await HANDLERS[topic](interno, ReclamoService(session, publisher))
    except Exception:
        EVENTOS_RECIBIDOS.labels(topic, "error").inc()
        raise

    EVENTOS_RECIBIDOS.labels(topic, "procesado").inc()
    log.info("webhook.evento_procesado", topic=topic, event_id=interno["event_id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
