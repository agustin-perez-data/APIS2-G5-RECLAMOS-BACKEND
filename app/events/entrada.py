"""Translation of an event of the CityPass+ bus into our internal envelope.

The bus speaks its own envelope, `{"metadata": {eventId, eventType, source,
receivedAt}, "data": {...}}`, whatever road the event takes: the webhook the
gateway's dispatcher calls (ADR 0009) and the Kafka topic it is written to
(ADR 0023) carry the same thing. Both roads translate it here, so an event
means the same on either and the handlers never learn which one it came by.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.events import topics


def a_sobre_interno(sobre: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Bus envelope -> (internal topic, internal envelope). None = ignore it."""
    metadata = sobre.get("metadata") or {}
    datos = sobre.get("data")
    tipo = metadata.get("eventType")
    event_id = metadata.get("eventId")
    if not tipo or not event_id or not isinstance(datos, dict):
        raise ValueError("El evento no trae metadata.eventId, metadata.eventType o data")

    topic = topics.GATEWAY_A_TOPIC.get(tipo)
    if topic is None:
        return None

    # Waste publishes fire alerts with the same type: only saturation is a claim.
    if topic == topics.RESIDUOS_CONTENEDOR_DESBORDADO and datos.get("tipoAlerta") != "SATURACION":
        return None

    recibido = metadata.get("receivedAt")
    ocurrido = (
        datetime.fromtimestamp(recibido / 1000, tz=UTC)
        if isinstance(recibido, int | float)
        else datetime.now(UTC)
    )
    return topic, {
        "event_id": event_id,
        "event_type": topic,
        "occurred_at": ocurrido.isoformat(),
        "source": metadata.get("source") or tipo.rsplit(".", 2)[-2],
        "correlation_id": datos.get("correlationId"),
        "data": datos,
    }
