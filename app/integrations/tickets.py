"""Tickets in the city's issue tracker for every new claim.

The service depends on the `SistemaTickets` port, not on Jira, for the same
reason it depends on `EventPublisher` instead of Kafka: the test suite never
reaches the network, and swapping the tracker is a one-class change.

The call is made after the claim is committed (see `ReclamoService.crear`), so
a tracker outage can never undo or block the filing of a claim. See
`docs/adr/0006-tickets-en-jira.md` for why it is not driven by events yet.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import Settings, settings
from app.domain.enums import CanalOrigen, CategoriaReclamo, PrioridadReclamo

# Jira's default priority scheme (Highest=1 ... Lowest=5), confirmed on the
# REC project. Ids rather than names: the names are shown translated.
PRIORIDAD_JIRA: dict[PrioridadReclamo, str] = {
    PrioridadReclamo.CRITICA: "1",
    PrioridadReclamo.ALTA: "2",
    PrioridadReclamo.MEDIA: "3",
    PrioridadReclamo.BAJA: "4",
}

# Jira caps the summary at 255 characters.
LARGO_MAXIMO_RESUMEN = 255


class ErrorTickets(Exception):
    """The tracker refused the ticket or could not be reached."""


@dataclass(frozen=True, slots=True)
class TicketNuevo:
    """What the tracker needs to know about a claim, decoupled from the ORM."""

    reclamo_id: uuid.UUID
    titulo: str
    descripcion: str
    categoria: CategoriaReclamo
    prioridad: PrioridadReclamo
    canal: CanalOrigen
    direccion: str | None
    barrio: str | None
    creado_at: datetime


class SistemaTickets(ABC):
    """Outbound port towards the issue tracker."""

    @abstractmethod
    async def crear(self, ticket: TicketNuevo) -> str | None:
        """Open the ticket. Returns its key (e.g. `REC-12`), or None if disabled."""


class SinTickets(SistemaTickets):
    """Used when JIRA_ENABLED=false: filing a claim opens nothing."""

    async def crear(self, ticket: TicketNuevo) -> str | None:
        return None


class TicketsEnMemoria(SistemaTickets):
    """Test double: records every ticket and hands out sequential keys."""

    def __init__(self, *, falla: bool = False) -> None:
        self.creados: list[TicketNuevo] = []
        self._falla = falla

    async def crear(self, ticket: TicketNuevo) -> str | None:
        if self._falla:
            raise ErrorTickets("Jira no responde (simulado)")
        self.creados.append(ticket)
        return f"REC-{len(self.creados)}"


class JiraTickets(SistemaTickets):
    """Opens tickets through Jira Cloud's REST API v3."""

    def __init__(
        self,
        cfg: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._cfg = cfg or settings
        # Tests inject httpx.MockTransport here; production uses the network.
        self._transport = transport

    async def crear(self, ticket: TicketNuevo) -> str | None:
        cfg = self._cfg
        # One client per ticket: claims arrive a few times an hour, so pooling
        # connections would not pay for the lifecycle it needs.
        async with httpx.AsyncClient(
            base_url=str(cfg.jira_url).rstrip("/"),
            auth=(str(cfg.jira_email), str(cfg.jira_api_token)),
            timeout=cfg.jira_timeout_segundos,
            headers={"Accept": "application/json"},
            transport=self._transport,
        ) as client:
            try:
                respuesta = await client.post("/rest/api/3/issue", json=self.payload(ticket))
            except httpx.HTTPError as exc:
                raise ErrorTickets(f"No se pudo contactar a Jira: {exc!r}") from exc

        if respuesta.status_code != httpx.codes.CREATED:
            # Jira explains a refusal in the body (missing field, bad issue type).
            raise ErrorTickets(f"Jira respondio {respuesta.status_code}: {respuesta.text[:300]}")
        return str(respuesta.json()["key"])

    def payload(self, ticket: TicketNuevo) -> dict[str, Any]:
        resumen = f"[{ticket.categoria.value}] {ticket.titulo}"
        return {
            "fields": {
                "project": {"key": self._cfg.jira_project_key},
                "issuetype": {"name": self._cfg.jira_issue_type},
                "summary": resumen[:LARGO_MAXIMO_RESUMEN],
                "priority": {"id": PRIORIDAD_JIRA[ticket.prioridad]},
                # Labels cannot contain spaces; the category values have none.
                "labels": ["reclamos-api", ticket.categoria.value.lower()],
                "description": _documento(_parrafos(ticket)),
            }
        }


def _parrafos(ticket: TicketNuevo) -> list[str]:
    ubicacion = ", ".join(parte for parte in (ticket.direccion, ticket.barrio) if parte)
    # The citizen's id is left out on purpose: the tracker is a third-party
    # tool, and the claim id is enough to find everything else in our system.
    return [
        ticket.descripcion,
        f"Reclamo: {ticket.reclamo_id}",
        f"Categoria: {ticket.categoria.value} | Prioridad: {ticket.prioridad.value}",
        f"Ubicacion: {ubicacion}" if ubicacion else "",
        f"Canal: {ticket.canal.value} | Creado: {ticket.creado_at.isoformat()}",
    ]


def _documento(parrafos: list[str]) -> dict[str, Any]:
    """Wrap plain text in Atlassian Document Format, which API v3 requires."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": texto}]}
            # ADF rejects empty text nodes.
            for texto in parrafos
            if texto
        ],
    }


@lru_cache
def get_sistema_tickets() -> SistemaTickets:
    """One per process, chosen by configuration."""
    return JiraTickets(settings) if settings.jira_enabled else SinTickets()
