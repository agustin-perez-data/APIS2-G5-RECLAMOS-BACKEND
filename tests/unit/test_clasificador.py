"""Tests for the automatic classifier (category + priority)."""

from __future__ import annotations

import pytest

from app.domain.enums import CategoriaReclamo, PrioridadReclamo
from app.ml.naive_bayes import MultinomialNaiveBayes
from app.ml.text import normalizar, tokenizar
from app.services.clasificador import ClasificadorNaiveBayes, get_clasificador


@pytest.fixture(scope="module")
def clasificador() -> ClasificadorNaiveBayes:
    return ClasificadorNaiveBayes()


@pytest.mark.parametrize(
    ("titulo", "descripcion", "esperada"),
    [
        (
            "Luminaria apagada",
            "El foco del poste de la esquina no enciende hace dos semanas",
            CategoriaReclamo.ALUMBRADO,
        ),
        (
            "Pozo en la calle",
            "Hay un bache muy profundo en el asfalto que rompe los autos",
            CategoriaReclamo.BACHES,
        ),
        (
            "Basura acumulada",
            "El contenedor esta desbordado y no pasa el camion recolector",
            CategoriaReclamo.RESIDUOS,
        ),
        (
            "Perdida de agua",
            "Sale agua del caño en la vereda y la cloaca desborda",
            CategoriaReclamo.AGUA_CLOACAS,
        ),
        (
            "Musica fuerte",
            "El boliche pone musica a todo volumen hasta la madrugada",
            CategoriaReclamo.RUIDOS,
        ),
        (
            "Semaforo roto",
            "El semaforo de la avenida no funciona y falta senalizacion",
            CategoriaReclamo.TRANSITO,
        ),
    ],
)
def test_predice_la_categoria_esperada(clasificador, titulo, descripcion, esperada) -> None:
    assert clasificador.clasificar(titulo, descripcion).categoria is esperada


def test_terminos_criticos_fuerzan_prioridad_critica(clasificador) -> None:
    sugerencia = clasificador.clasificar(
        "Olor a gas",
        "Hay una fuga de gas en la vereda, riesgo de explosion para los vecinos",
    )
    assert sugerencia.prioridad is PrioridadReclamo.CRITICA
    assert sugerencia.evidencia, "the suggestion must justify itself"


def test_categoria_de_base_define_prioridad_sin_terminos_de_urgencia(clasificador) -> None:
    # Neutral wording: priority must fall back to the category baseline.
    sugerencia = clasificador.clasificar(
        "Consulta de tramite",
        "Queria saber como sigue mi expediente en la oficina municipal",
    )
    assert sugerencia.categoria is CategoriaReclamo.OTROS
    assert sugerencia.prioridad is PrioridadReclamo.BAJA


def test_seguridad_nunca_baja_de_alta(clasificador) -> None:
    sugerencia = clasificador.clasificar(
        "Robos en la parada",
        "Hubo varios arrebatos y pedimos mas patrullaje policial en la zona",
    )
    assert sugerencia.categoria is CategoriaReclamo.SEGURIDAD
    assert sugerencia.prioridad in {PrioridadReclamo.ALTA, PrioridadReclamo.CRITICA}


def test_texto_vacio_cae_en_otros(clasificador) -> None:
    sugerencia = clasificador.clasificar("...", "!!!")
    assert sugerencia.categoria is CategoriaReclamo.OTROS
    assert sugerencia.confianza == 0.0


def test_la_confianza_esta_normalizada(clasificador) -> None:
    sugerencia = clasificador.clasificar("Bache", "Pozo profundo en el asfalto de la calle")
    assert 0.0 <= sugerencia.confianza <= 1.0


def test_get_clasificador_es_singleton() -> None:
    # Training on every request would be absurd; the factory must cache.
    assert get_clasificador() is get_clasificador()


# --- Naive Bayes internals ---------------------------------------------------
def test_probabilidades_suman_uno() -> None:
    modelo = MultinomialNaiveBayes().fit(
        [(["bache", "pozo"], "BACHES"), (["luz", "foco"], "ALUMBRADO")]
    )
    probabilidades = modelo.predict_proba(["bache"])
    assert pytest.approx(sum(probabilidades.values()), abs=1e-9) == 1.0


def test_tokens_desconocidos_no_rompen_la_prediccion() -> None:
    modelo = MultinomialNaiveBayes().fit(
        [(["bache", "pozo"], "BACHES"), (["luz", "foco"], "ALUMBRADO")]
    )
    etiqueta, confianza = modelo.predict(["palabraquenoexiste"])
    assert etiqueta in {"BACHES", "ALUMBRADO"}
    assert 0.0 <= confianza <= 1.0


def test_corpus_vacio_es_error() -> None:
    with pytest.raises(ValueError):
        MultinomialNaiveBayes().fit([])


# --- Text preprocessing ------------------------------------------------------
def test_normalizar_saca_tildes_y_puntuacion() -> None:
    assert normalizar("¡Camión ROTO, en la esquina!") == "camion roto en la esquina"


def test_tokenizar_arma_bigramas_y_saca_stopwords() -> None:
    tokens = tokenizar("el camion de la basura no pasa")
    assert "camion" in tokens
    assert "basura_pasa" in tokens
    # "de", "la", "no" are stopwords and must be gone.
    assert "de" not in tokens
