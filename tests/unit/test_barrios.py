"""The neighbourhood a neighbour typed, against the ones Public Spaces sent.

This is the primary cross of the weather alert mode, so what it does and what it
deliberately does not do both belong in tests.
"""

from __future__ import annotations

import pytest

from app.domain.barrios import barrio_afectado, normalizar_barrio


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Palermo", "PALERMO"),
        ("palermo", "PALERMO"),
        ("PALERMO", "PALERMO"),
        ("  Villa Crespo  ", "VILLA CRESPO"),
        ("Villa   Crespo", "VILLA CRESPO"),
        ("Villa\nCrespo", "VILLA CRESPO"),
        ("Núñez", "NUÑEZ"),
        ("NUÑEZ", "NUÑEZ"),
        ("Constitución", "CONSTITUCION"),
    ],
)
def test_normaliza_mayusculas_tildes_y_espacios(texto: str, esperado: str) -> None:
    assert normalizar_barrio(texto) == esperado


def test_la_enie_no_se_convierte_en_ene() -> None:
    # Stripping every combining mark would turn Nuñez into NUNEZ, which is a
    # different word: the tilde of the n is part of the letter, not an accent.
    assert normalizar_barrio("Nuñez") == "NUÑEZ"
    assert normalizar_barrio("Nunez") == "NUNEZ"
    assert normalizar_barrio("Nuñez") != normalizar_barrio("Nunez")


@pytest.mark.parametrize("texto", [None, "", "   ", "\n"])
def test_sin_nada_que_comparar_devuelve_none(texto: str | None) -> None:
    assert normalizar_barrio(texto) is None


def test_el_barrio_del_reclamo_entra_aunque_este_escrito_distinto() -> None:
    assert barrio_afectado("palermo", ["PALERMO", "BELGRANO"])
    assert barrio_afectado("  Belgrano ", ["PALERMO", "BELGRANO"])
    assert barrio_afectado("Constitución", ["constitucion"])


def test_un_barrio_fuera_de_la_alerta_no_entra() -> None:
    assert not barrio_afectado("Caballito", ["PALERMO", "BELGRANO"])


def test_el_reclamo_sin_barrio_no_entra() -> None:
    # It is not a mistake: a claim with no neighbourhood cannot be placed, and
    # it gets counted apart as "sin ubicacion" rather than guessed into an alert.
    assert not barrio_afectado(None, ["PALERMO"])
    assert not barrio_afectado("   ", ["PALERMO"])


def test_una_alerta_sin_barrios_no_marca_nada() -> None:
    # The list arrives empty when Public Spaces did not work out the area. The
    # geographic fallback handles that case; here nothing matches.
    assert not barrio_afectado("Palermo", [])


def test_normalizar_NO_corrige_errores_de_tipeo() -> None:
    # Documented on purpose. A fuzzy match would quietly decide that two
    # neighbourhoods are the same, and a wrong match is worse than a claim left
    # out: nobody would ever find out. If this starts mattering, the fix is to
    # stop letting the neighbour type the neighbourhood, not to guess here.
    assert not barrio_afectado("Plaermo", ["PALERMO"])
    assert not barrio_afectado("Balgrano", ["BELGRANO"])
