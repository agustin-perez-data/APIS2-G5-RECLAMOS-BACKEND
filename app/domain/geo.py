"""Plain geography over latitude/longitude: no GIS extension needed.

Pure functions on purpose: they run the same on PostgreSQL and on the SQLite
the test suite uses, and they are testable without a database.
"""

from __future__ import annotations

import math

RADIO_TIERRA_METROS = 6_371_000
# Length of one degree of latitude. A degree of longitude shrinks with the
# cosine of the latitude, which is why the bounding box below widens it.
METROS_POR_GRADO_LATITUD = 111_320


def distancia_metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine). Accurate to meters at city scale."""
    fi1, fi2 = math.radians(lat1), math.radians(lat2)
    delta_fi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_fi / 2) ** 2
        + math.cos(fi1) * math.cos(fi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * RADIO_TIERRA_METROS * math.asin(math.sqrt(a))


def caja_alrededor(
    lat: float, lon: float, radio_metros: float
) -> tuple[float, float, float, float]:
    """Bounding box (lat_min, lat_max, lon_min, lon_max) that contains the circle.

    Lets the database discard far-away rows with plain range comparisons; the
    exact distance is then computed only for the few rows inside the box.
    """
    delta_lat = radio_metros / METROS_POR_GRADO_LATITUD
    # Guard against the poles, where the cosine goes to zero.
    coseno = max(math.cos(math.radians(lat)), 1e-6)
    delta_lon = radio_metros / (METROS_POR_GRADO_LATITUD * coseno)
    return lat - delta_lat, lat + delta_lat, lon - delta_lon, lon + delta_lon
