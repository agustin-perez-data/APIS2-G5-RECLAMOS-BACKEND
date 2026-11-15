"""Quality gate for the classifier (ADR 0019).

These are not unit tests of the code: they fail when the MODEL gets worse.
Touching the corpus, the tokenizer or the model's configuration in a way that
drops it below these floors breaks the build, the same way a regression in
behaviour would.

The floors sit a few points under the values in
`docs/ml/evaluacion-clasificador.md`. They are a safety net, not a target: when
the model improves, regenerate the report and raise them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.domain.enums import CategoriaReclamo
from app.ml.corpus import CORPUS, CORPUS_SEMILLA
from app.ml.corpus_ampliado import AMPLIACION
from app.ml.evaluacion import (
    Ejemplo,
    Prediccion,
    cargar_tsv,
    curva_riesgo_cobertura,
    evaluar,
    predecir_conjunto,
)
from app.ml.text import tokenizar
from app.services.clasificador import ClasificadorNaiveBayes, get_clasificador

DATOS = Path(__file__).resolve().parent.parent / "datos" / "clasificador"

PISO_F1_INDEPENDIENTE = 0.92
PISO_F1_POR_CATEGORIA = 0.80
PISO_EXACTITUD_REAL = 0.90
PISO_EXACTITUD_ENTRE_AUTORES = 0.88
RIESGO_MAXIMO = 0.05
CERCANIA_MAXIMA = 0.8


@pytest.fixture(scope="module")
def independiente() -> list[Ejemplo]:
    return cargar_tsv(DATOS / "prueba_independiente.tsv")


@pytest.fixture(scope="module")
def real() -> list[Ejemplo]:
    return cargar_tsv(DATOS / "prueba_real.tsv")


@pytest.fixture(scope="module")
def pred_independiente(independiente) -> list[Prediccion]:
    return predecir_conjunto(independiente, get_clasificador().predecir)


@pytest.fixture(scope="module")
def pred_real(real) -> list[Prediccion]:
    return predecir_conjunto(real, get_clasificador().predecir)


def test_el_conjunto_independiente_cubre_las_diez_categorias(independiente) -> None:
    por_categoria: dict[str, int] = {}
    for _, etiqueta in independiente:
        por_categoria[etiqueta] = por_categoria.get(etiqueta, 0) + 1

    assert por_categoria == {categoria.value: 10 for categoria in CategoriaReclamo}


def test_f1_macro_sobre_el_conjunto_independiente(pred_independiente) -> None:
    assert evaluar(pred_independiente).f1_macro >= PISO_F1_INDEPENDIENTE


def test_ninguna_categoria_queda_abandonada(pred_independiente) -> None:
    por_clase = evaluar(pred_independiente).por_clase
    flojas = {
        clase: round(m.f1, 2) for clase, m in por_clase.items() if m.f1 < PISO_F1_POR_CATEGORIA
    }

    assert not flojas, f"Categorias por debajo de F1 {PISO_F1_POR_CATEGORIA}: {flojas}"


def test_exactitud_sobre_textos_reales_de_produccion(pred_real) -> None:
    assert evaluar(pred_real).exactitud >= PISO_EXACTITUD_REAL


def test_generaliza_a_frases_escritas_por_otras_personas() -> None:
    # Trained only on the second batch, tested on the seed corpus, which other
    # people wrote before it. The closest thing here to an unseen author.
    modelo = ClasificadorNaiveBayes(corpus=AMPLIACION)
    semilla = [(texto, categoria.value) for texto, categoria in CORPUS_SEMILLA]

    assert evaluar(predecir_conjunto(semilla, modelo.predecir)).exactitud >= (
        PISO_EXACTITUD_ENTRE_AUTORES
    )


@pytest.mark.parametrize("conjunto", ["pred_independiente", "pred_real"])
def test_el_umbral_en_uso_mantiene_el_riesgo_acotado(conjunto: str, request) -> None:
    predicciones = request.getfixturevalue(conjunto)
    (punto,) = curva_riesgo_cobertura(predicciones, [settings.confianza_minima_clasificador])

    # Risk: claims routed to the wrong department with no human looking.
    assert punto.riesgo <= RIESGO_MAXIMO
    # And the threshold must not buy that by sending everything to review.
    assert punto.cobertura >= 0.80


def test_ninguna_frase_de_la_ampliacion_copia_un_texto_de_prueba(independiente, real) -> None:
    def raices(texto: str) -> set[str]:
        return set(tokenizar(texto, con_bigramas=False, con_raices=True))

    pruebas = [raices(texto) for texto, _ in independiente + real]
    copias = []
    for texto, _ in AMPLIACION:
        propias = raices(texto)
        cercania = max(len(propias & prueba) / len(propias) for prueba in pruebas)
        if cercania >= CERCANIA_MAXIMA:
            copias.append(texto)

    assert not copias, f"Frases de entrenamiento demasiado parecidas a la prueba: {copias}"


def test_el_corpus_no_tiene_frases_repetidas_ni_categorias_vacias() -> None:
    textos = [texto for texto, _ in CORPUS]
    por_categoria = dict.fromkeys(CategoriaReclamo, 0)
    for _, categoria in CORPUS:
        por_categoria[categoria] += 1

    assert len(textos) == len(set(textos))
    assert min(por_categoria.values()) >= 30
