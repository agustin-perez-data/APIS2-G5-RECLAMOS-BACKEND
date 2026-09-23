"""Jira adapter tests: the request we send, and how refusals surface.

The network is replaced with httpx.MockTransport, so these check the exact
payload Jira receives without opening a real ticket.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.core.config import Settings
from app.domain.enums import CanalOrigen, CategoriaReclamo, PrioridadReclamo
from app.integrations.tickets import (
    ErrorTickets,
    JiraTickets,
    SinTickets,
    TicketNuevo,
    get_sistema_tickets,
)

RECLAMO_ID = uuid.UUID("6f1c9a4e-3c2b-4a5d-9e11-2b7d5c8a1f30")


def config_jira(**overrides) -> Settings:
    base = {
        "environment": "test",
        "jira_enabled": True,
        "jira_url": "https://grupo-5-da2.atlassian.net",
        "jira_email": "equipo@uade.edu.ar",
        "jira_api_token": "token-de-prueba",
    }
    base.update(overrides)
    return Settings(**base)


def ticket(**overrides) -> TicketNuevo:
    base = {
        "reclamo_id": RECLAMO_ID,
        "titulo": "Luminaria apagada en la plaza",
        "descripcion": "El foco del poste no enciende hace dos semanas",
        "categoria": CategoriaReclamo.ALUMBRADO,
        "prioridad": PrioridadReclamo.CRITICA,
        "canal": CanalOrigen.APP,
        "direccion": "Rivadavia 800",
        "barrio": "Centro",
        "creado_at": datetime(2026, 9, 23, 14, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return TicketNuevo(**base)


def textos(descripcion: dict) -> list[str]:
    return [p["content"][0]["text"] for p in descripcion["content"]]


# --- Payload -----------------------------------------------------------------
def test_el_payload_arma_el_ticket_en_el_proyecto_y_tipo_configurados() -> None:
    campos = JiraTickets(config_jira()).payload(ticket())["fields"]

    assert campos["project"] == {"key": "REC"}
    assert campos["issuetype"] == {"name": "Tarea"}
    assert campos["summary"] == "[ALUMBRADO] Luminaria apagada en la plaza"
    assert campos["labels"] == ["reclamos-api", "alumbrado"]


@pytest.mark.parametrize(
    ("prioridad", "id_jira"),
    [
        (PrioridadReclamo.CRITICA, "1"),
        (PrioridadReclamo.ALTA, "2"),
        (PrioridadReclamo.MEDIA, "3"),
        (PrioridadReclamo.BAJA, "4"),
    ],
)
def test_la_prioridad_se_traduce_al_esquema_de_jira(
    prioridad: PrioridadReclamo, id_jira: str
) -> None:
    campos = JiraTickets(config_jira()).payload(ticket(prioridad=prioridad))["fields"]
    assert campos["priority"] == {"id": id_jira}


def test_la_descripcion_es_adf_y_referencia_el_reclamo() -> None:
    descripcion = JiraTickets(config_jira()).payload(ticket())["fields"]["description"]

    assert descripcion["type"] == "doc"
    lineas = textos(descripcion)
    assert lineas[0] == "El foco del poste no enciende hace dos semanas"
    assert f"Reclamo: {RECLAMO_ID}" in lineas
    assert "Ubicacion: Rivadavia 800, Centro" in lineas


def test_sin_ubicacion_no_quedan_parrafos_vacios() -> None:
    # ADF rejects empty text nodes: Jira would answer 400.
    payload = JiraTickets(config_jira()).payload(ticket(direccion=None, barrio=None))
    descripcion = payload["fields"]["description"]
    assert all(texto for texto in textos(descripcion))
    assert not any(texto.startswith("Ubicacion") for texto in textos(descripcion))


def test_el_resumen_se_corta_en_el_limite_de_jira() -> None:
    campos = JiraTickets(config_jira()).payload(ticket(titulo="x" * 400))["fields"]
    assert len(campos["summary"]) == 255


# --- Request -----------------------------------------------------------------
async def test_crear_postea_con_basic_auth_y_devuelve_la_clave() -> None:
    recibido: dict = {}

    def jira(request: httpx.Request) -> httpx.Response:
        recibido["url"] = str(request.url)
        recibido["auth"] = request.headers["authorization"]
        recibido["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "10001", "key": "REC-7"})

    clave = await JiraTickets(config_jira(), transport=httpx.MockTransport(jira)).crear(ticket())

    assert clave == "REC-7"
    assert recibido["url"] == "https://grupo-5-da2.atlassian.net/rest/api/3/issue"
    esperado = base64.b64encode(b"equipo@uade.edu.ar:token-de-prueba").decode()
    assert recibido["auth"] == f"Basic {esperado}"
    assert recibido["body"]["fields"]["project"] == {"key": "REC"}


async def test_un_rechazo_de_jira_se_informa_con_su_motivo() -> None:
    def jira(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"errors": {"issuetype": "Tipo de incidencia invalido"}})

    with pytest.raises(ErrorTickets, match="400.*issuetype"):
        await JiraTickets(config_jira(), transport=httpx.MockTransport(jira)).crear(ticket())


async def test_si_jira_no_responde_se_levanta_error_de_tickets() -> None:
    def jira(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout", request=request)

    with pytest.raises(ErrorTickets, match="No se pudo contactar"):
        await JiraTickets(config_jira(), transport=httpx.MockTransport(jira)).crear(ticket())


# --- Configuration -------------------------------------------------------------
def test_jira_encendido_sin_credenciales_no_arranca() -> None:
    with pytest.raises(ValueError, match="JIRA_API_TOKEN"):
        config_jira(jira_api_token=None)


def test_con_jira_apagado_no_se_abren_tickets() -> None:
    # conftest turns Jira off: the suite must never talk to the real tracker.
    assert isinstance(get_sistema_tickets(), SinTickets)
