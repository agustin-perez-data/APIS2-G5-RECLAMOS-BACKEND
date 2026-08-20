"""Tests for the state machine and priority rules."""

from __future__ import annotations

import pytest

from app.domain.enums import (
    ESTADOS_FINALES,
    EstadoReclamo,
    PrioridadReclamo,
    escalar,
    puede_transicionar,
)


@pytest.mark.parametrize(
    ("desde", "hacia"),
    [
        (EstadoReclamo.RECIBIDO, EstadoReclamo.EN_REVISION),
        (EstadoReclamo.RECIBIDO, EstadoReclamo.ASIGNADO),
        (EstadoReclamo.ASIGNADO, EstadoReclamo.EN_PROCESO),
        (EstadoReclamo.EN_PROCESO, EstadoReclamo.RESUELTO),
        (EstadoReclamo.RESUELTO, EstadoReclamo.CERRADO),
    ],
)
def test_transiciones_validas(desde, hacia) -> None:
    assert puede_transicionar(desde, hacia)


@pytest.mark.parametrize(
    ("desde", "hacia"),
    [
        (EstadoReclamo.RECIBIDO, EstadoReclamo.RESUELTO),
        (EstadoReclamo.RECIBIDO, EstadoReclamo.CERRADO),
        (EstadoReclamo.CERRADO, EstadoReclamo.EN_PROCESO),
        (EstadoReclamo.RECHAZADO, EstadoReclamo.ASIGNADO),
    ],
)
def test_transiciones_invalidas(desde, hacia) -> None:
    assert not puede_transicionar(desde, hacia)


def test_los_estados_finales_no_tienen_salida() -> None:
    for estado in ESTADOS_FINALES:
        assert not any(puede_transicionar(estado, otro) for otro in EstadoReclamo)


def test_escalar_nunca_baja_la_prioridad() -> None:
    assert escalar(PrioridadReclamo.CRITICA, PrioridadReclamo.ALTA) is PrioridadReclamo.CRITICA
    assert escalar(PrioridadReclamo.BAJA, PrioridadReclamo.ALTA) is PrioridadReclamo.ALTA
    assert escalar(PrioridadReclamo.MEDIA, PrioridadReclamo.MEDIA) is PrioridadReclamo.MEDIA
