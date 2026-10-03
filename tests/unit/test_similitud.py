"""Text similarity between claims (TF-IDF + cosine)."""

from __future__ import annotations

import pytest

from app.ml.similitud import raiz, similitudes, terminos_en_comun, tokens

CONSULTA = (
    "Luminaria apagada en la esquina. La luz de la esquina de Rivadavia y Medrano no anda hace dias"
)
MISMO_PROBLEMA = (
    "Poste de luz apagado. El foco de la esquina de Rivadavia y Medrano esta apagado desde el lunes"
)
OTRO_PROBLEMA = "Reflector quemado. Reflector del playon deportivo sin funcionar"


@pytest.mark.parametrize(
    ("una", "otra"),
    [("postes", "poste"), ("apagada", "apagado"), ("luminarias", "luminaria"), ("fugas", "fuga")],
)
def test_las_variantes_de_una_palabra_comparten_raiz(una: str, otra: str) -> None:
    assert raiz(una) == raiz(otra)


def test_las_palabras_cortas_no_se_mutilan() -> None:
    assert raiz("gas") == "gas"
    assert raiz("luz") == "luz"


def test_un_texto_es_identico_a_si_mismo() -> None:
    assert similitudes(tokens(CONSULTA), [tokens(CONSULTA)])[0] == pytest.approx(1.0)


def test_textos_sin_palabras_en_comun_no_se_parecen() -> None:
    assert similitudes(tokens(CONSULTA), [tokens(OTRO_PROBLEMA)]) == [0.0]


def test_el_mismo_problema_se_parece_mas_que_otro() -> None:
    mismo, otro = similitudes(tokens(CONSULTA), [tokens(MISMO_PROBLEMA), tokens(OTRO_PROBLEMA)])
    assert mismo > 0.2
    assert mismo > otro


def test_una_palabra_que_tienen_todos_pesa_menos_que_una_rara() -> None:
    # "calle" is in every document: IDF makes "bache" decide the match.
    consulta = tokens("bache calle")
    con_bache, sin_bache = similitudes(
        consulta, [tokens("bache enorme calle"), tokens("arbol caido calle")]
    )
    assert con_bache > sin_bache


def test_sin_candidatos_no_hay_similitudes() -> None:
    assert similitudes(tokens(CONSULTA), []) == []


def test_los_terminos_en_comun_salen_legibles_y_acotados() -> None:
    comunes = terminos_en_comun(CONSULTA, MISMO_PROBLEMA, limite=3)

    assert len(comunes) == 3
    # As the candidate writes them, not stems: "apagado", never "apagad".
    assert all(len(palabra) > 2 and not palabra.endswith("_") for palabra in comunes)
    assert "luz" in comunes
