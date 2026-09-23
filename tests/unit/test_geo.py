"""Distances and bounding boxes used to find nearby claims."""

from __future__ import annotations

import pytest

from app.domain.geo import METROS_POR_GRADO_LATITUD, caja_alrededor, distancia_metros

ALMAGRO = (-34.6037, -58.4201)


def al_norte(punto: tuple[float, float], metros: float) -> tuple[float, float]:
    lat, lon = punto
    return lat + metros / METROS_POR_GRADO_LATITUD, lon


def test_la_distancia_a_uno_mismo_es_cero() -> None:
    assert distancia_metros(*ALMAGRO, *ALMAGRO) == 0


def test_un_grado_de_latitud_mide_unos_111_km() -> None:
    assert distancia_metros(0, 0, 1, 0) == pytest.approx(111_195, rel=0.005)


def test_la_distancia_a_escala_de_cuadra_es_precisa() -> None:
    assert distancia_metros(*ALMAGRO, *al_norte(ALMAGRO, 300)) == pytest.approx(300, abs=2)


def test_la_caja_contiene_el_circulo_y_deja_afuera_lo_lejano() -> None:
    lat_min, lat_max, lon_min, lon_max = caja_alrededor(*ALMAGRO, 300)

    lat_cerca, lon_cerca = al_norte(ALMAGRO, 290)
    lat_lejos, _ = al_norte(ALMAGRO, 400)

    assert lat_min <= lat_cerca <= lat_max
    assert lon_min <= lon_cerca <= lon_max
    assert not lat_min <= lat_lejos <= lat_max


def test_la_caja_se_ensancha_en_longitud_lejos_del_ecuador() -> None:
    # A degree of longitude is shorter in Buenos Aires than at the equator.
    _, _, lon_min_ecuador, lon_max_ecuador = caja_alrededor(0, 0, 300)
    _, _, lon_min_bsas, lon_max_bsas = caja_alrededor(*ALMAGRO, 300)
    assert (lon_max_bsas - lon_min_bsas) > (lon_max_ecuador - lon_min_ecuador)
