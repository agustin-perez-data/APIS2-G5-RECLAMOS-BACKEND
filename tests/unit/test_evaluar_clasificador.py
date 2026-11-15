"""The evaluation script: it runs, it is deterministic, and its guard works."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

from app.ml.naive_bayes import ComplementNaiveBayes

RAIZ = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "evaluar_clasificador", RAIZ / "scripts" / "evaluar_clasificador.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    # Dataclasses look their module up in sys.modules while being built.
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def corrida(script):
    return script.generar()


def test_el_reporte_trae_todas_sus_secciones(corrida) -> None:
    reporte, _ = corrida

    for seccion in (
        "## Resultado",
        "### Qué tan optimista es ese número",
        "## Datos",
        "## Selección del modelo",
        "## Cuánto aportó ampliar el corpus",
        "## Resultado por categoría",
        "### Matriz de confusión",
        "## Calibración de la confianza",
        "## Umbral de revisión humana",
    ):
        assert seccion in reporte


def test_la_corrida_es_deterministica(script, corrida) -> None:
    assert script.generar() == corrida


def test_el_reporte_versionado_esta_al_dia(corrida) -> None:
    # If this fails, the corpus or the model changed and nobody re-ran
    # `python scripts/evaluar_clasificador.py`.
    reporte, _ = corrida
    versionado = (RAIZ / "docs" / "ml" / "evaluacion-clasificador.md").read_text(encoding="utf-8")

    assert versionado == reporte


def test_lo_que_esta_en_produccion_es_lo_que_eligio_la_evaluacion(script, corrida) -> None:
    _, numeros = corrida
    elegida = next(v for v in script.variantes() if v.nombre == numeros["elegida"])
    en_produccion = script.ClasificadorNaiveBayes()

    assert numeros["umbral"] == numeros["umbral_configurado"]
    assert en_produccion._modelo.temperatura == numeros["temperatura"]
    assert en_produccion._modelo.alpha == elegida.alpha
    assert en_produccion._con_raices == elegida.con_raices
    assert en_produccion._con_bigramas == elegida.con_bigramas
    assert isinstance(en_produccion._modelo, ComplementNaiveBayes) == elegida.complementario


def test_la_primera_variante_es_la_configuracion_anterior(script) -> None:
    original = script.variantes()[0]

    assert (original.alpha, original.con_bigramas, original.con_raices) == (0.3, True, False)
    assert not original.complementario
    assert len(script.variantes()) == 24


def test_el_control_de_fuga_detecta_una_copia_y_deja_pasar_lo_distinto(script) -> None:
    prueba = [("Semaforo apagado en el cruce de la avenida principal", "TRANSITO")]

    copias = script.copias_cercanas(
        [
            ("El semaforo del cruce esta apagado", "TRANSITO"),  # same stems
            ("Hay un pozo profundo en la calzada", "BACHES"),
        ],
        prueba,
    )

    assert [texto for _, texto in copias] == ["El semaforo del cruce esta apagado"]


def test_la_referencia_de_palabras_clave_no_aprende_nada(script) -> None:
    predecir = script.predictor_palabras_clave([])

    assert predecir("Hay un bache en el asfalto")[0] == "BACHES"
    assert predecir("texto sin ninguna pista") == ("OTROS", 0.0)


def test_la_referencia_mayoritaria_contesta_siempre_lo_mismo(script) -> None:
    predecir = script.predictor_mayoritario([("a", "X"), ("b", "X"), ("c", "Y")])

    assert predecir("cualquier cosa") == ("X", 1.0)


def test_main_escribe_el_archivo(script, tmp_path) -> None:
    destino = tmp_path / "sub" / "reporte.md"

    assert script.main(["--salida", str(destino)]) == 0
    assert destino.read_text(encoding="utf-8").startswith("# Evaluación del clasificador")
