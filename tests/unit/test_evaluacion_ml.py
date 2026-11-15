"""Metrics used to evaluate the classifier (ADR 0019).

Every expected value here was worked out by hand: a metric that is wrong makes
every report built on it wrong, and nothing else would notice.
"""

from __future__ import annotations

import math

import pytest

from app.ml.evaluacion import (
    Prediccion,
    calibracion,
    cargar_tsv,
    curva_riesgo_cobertura,
    elegir_umbral,
    evaluar,
    intervalo_wilson,
    log_perdida,
    pliegues_estratificados,
    predecir_conjunto,
    validacion_cruzada,
)


def _p(real: str, predicha: str, confianza: float = 1.0) -> Prediccion:
    return Prediccion(real, predicha, confianza)


# --- evaluar -----------------------------------------------------------------


def test_exactitud_y_metricas_por_clase() -> None:
    # A: 2 right, 1 taken for B.  B: 1 right, 1 taken for A.
    reporte = evaluar([_p("A", "A"), _p("A", "A"), _p("A", "B"), _p("B", "B"), _p("B", "A")])

    assert reporte.total == 5
    assert reporte.aciertos == 3
    assert reporte.exactitud == pytest.approx(0.6)
    a, b = reporte.por_clase["A"], reporte.por_clase["B"]
    assert (a.precision, a.recall, a.soporte) == (pytest.approx(2 / 3), pytest.approx(2 / 3), 3)
    assert (b.precision, b.recall, b.soporte) == (pytest.approx(0.5), pytest.approx(0.5), 2)
    assert reporte.f1_macro == pytest.approx((2 / 3 + 0.5) / 2)


def test_una_clase_que_nunca_se_predice_tiene_f1_cero_y_baja_el_macro() -> None:
    # The model answers A for everything. Accuracy looks fine; macro F1 does not.
    reporte = evaluar([_p("A", "A")] * 9 + [_p("B", "A")])

    assert reporte.exactitud == pytest.approx(0.9)
    assert reporte.por_clase["B"].f1 == 0.0
    assert reporte.f1_macro < 0.5


def test_las_confusiones_salen_ordenadas_por_frecuencia() -> None:
    reporte = evaluar([_p("A", "B"), _p("A", "B"), _p("B", "C"), _p("A", "A")])

    assert reporte.confusiones() == [("A", "B", 2), ("B", "C", 1)]


def test_evaluar_sin_predicciones_es_un_error() -> None:
    with pytest.raises(ValueError, match="No hay predicciones"):
        evaluar([])


# --- intervalo de Wilson -----------------------------------------------------


def test_intervalo_de_wilson_contra_un_valor_conocido() -> None:
    # 8 of 10 at 95%: the textbook Wilson interval is (0.490, 0.943).
    bajo, alto = intervalo_wilson(8, 10)

    assert bajo == pytest.approx(0.490, abs=0.001)
    assert alto == pytest.approx(0.943, abs=0.001)


def test_el_intervalo_no_se_sale_de_cero_y_uno_ni_con_todo_acertado() -> None:
    bajo, alto = intervalo_wilson(28, 28)

    assert alto == 1.0
    assert 0.85 < bajo < 0.9  # still uncertain: 28 cases cannot prove 100%


def test_intervalo_sin_casos() -> None:
    assert intervalo_wilson(0, 0) == (0.0, 0.0)


# --- validacion cruzada ------------------------------------------------------


def test_los_pliegues_reparten_cada_clase_en_todos() -> None:
    etiquetas = ["A"] * 6 + ["B"] * 6
    pliegues = pliegues_estratificados(etiquetas, 3)

    assert sorted(i for pliegue in pliegues for i in pliegue) == list(range(12))
    for pliegue in pliegues:
        assert sorted(etiquetas[i] for i in pliegue) == ["A", "A", "B", "B"]


def test_los_pliegues_son_deterministicos() -> None:
    etiquetas = ["A", "B", "A", "C", "B", "A", "C", "B", "C"]

    assert pliegues_estratificados(etiquetas, 3) == pliegues_estratificados(etiquetas, 3)


def test_menos_de_dos_pliegues_es_un_error() -> None:
    with pytest.raises(ValueError, match="al menos 2"):
        pliegues_estratificados(["A", "B"], 1)


def test_cada_ejemplo_lo_predice_un_modelo_que_no_lo_vio() -> None:
    ejemplos = [(f"texto {i}", "A" if i % 2 else "B") for i in range(10)]
    vistos_al_predecir: list[tuple[str, frozenset[str]]] = []

    def entrenar(entrenamiento):
        conocidos = frozenset(texto for texto, _ in entrenamiento)

        def predecir(texto: str) -> tuple[str, float]:
            vistos_al_predecir.append((texto, conocidos))
            return "A", 0.5

        return predecir

    predicciones = validacion_cruzada(ejemplos, entrenar, k=5)

    assert len(predicciones) == len(ejemplos)
    assert sorted(texto for texto, _ in vistos_al_predecir) == sorted(t for t, _ in ejemplos)
    assert all(texto not in conocidos for texto, conocidos in vistos_al_predecir)


def test_predecir_conjunto_conserva_la_etiqueta_real() -> None:
    predicciones = predecir_conjunto([("uno", "A"), ("dos", "B")], lambda _t: ("A", 0.7))

    assert predicciones == [Prediccion("A", "A", 0.7), Prediccion("B", "A", 0.7)]


# --- umbral ------------------------------------------------------------------


def test_curva_de_riesgo_y_cobertura() -> None:
    predicciones = [
        _p("A", "A", 0.9),  # accepted, right
        _p("A", "B", 0.8),  # accepted, wrong
        _p("A", "A", 0.4),  # sent to review although it was right
        _p("A", "B", 0.2),  # sent to review, and it was wrong
    ]
    (punto,) = curva_riesgo_cobertura(predicciones, [0.5])

    assert punto.cobertura == pytest.approx(0.5)
    assert punto.riesgo == pytest.approx(0.25)
    assert punto.exactitud_aceptados == pytest.approx(0.5)
    assert punto.revision_innecesaria == pytest.approx(0.25)


def test_un_umbral_que_no_acepta_nada_no_divide_por_cero() -> None:
    (punto,) = curva_riesgo_cobertura([_p("A", "A", 0.3)], [0.9])

    assert punto.cobertura == 0.0
    assert punto.exactitud_aceptados == 0.0


def test_se_elige_el_umbral_mas_bajo_que_cumple_el_riesgo() -> None:
    predicciones = [_p("A", "B", 0.3), _p("A", "B", 0.5), _p("A", "A", 0.7), _p("A", "A", 0.9)]
    curva = curva_riesgo_cobertura(predicciones, [0.2, 0.4, 0.6, 0.8])

    # At 0.6 no wrong prediction slips through any more; 0.8 also qualifies
    # but would send a right one to review for nothing.
    assert elegir_umbral(curva, riesgo_maximo=0.0).umbral == 0.6


def test_sin_umbral_que_cumpla_devuelve_none() -> None:
    curva = curva_riesgo_cobertura([_p("A", "B", 0.99)], [0.5])

    assert elegir_umbral(curva, riesgo_maximo=0.0) is None


# --- calibracion -------------------------------------------------------------


def test_un_modelo_calibrado_tiene_error_cero() -> None:
    # Says 0.5 and is right half of the time.
    ece, tabla = calibracion([_p("A", "A", 0.5), _p("A", "B", 0.5)], tramos=5)

    assert ece == pytest.approx(0.0)
    assert [(t.cantidad, t.exactitud) for t in tabla] == [(2, 0.5)]


def test_el_exceso_de_confianza_se_mide() -> None:
    # Says 0.9 and is never right: off by 0.9.
    ece, _ = calibracion([_p("A", "B", 0.9), _p("A", "B", 0.9)])

    assert ece == pytest.approx(0.9)


def test_confianza_uno_cae_en_el_ultimo_tramo() -> None:
    _, tabla = calibracion([_p("A", "A", 1.0)], tramos=5)

    assert (tabla[0].desde, tabla[0].hasta) == (0.8, 1.0)


def test_log_perdida() -> None:
    assert log_perdida([1.0, 1.0]) == pytest.approx(0.0)
    assert log_perdida([0.5]) == pytest.approx(math.log(2))
    # A zero probability is floored instead of blowing up to infinity.
    assert math.isfinite(log_perdida([0.0]))


@pytest.mark.parametrize("funcion", [calibracion, log_perdida])
def test_sin_datos_es_un_error(funcion) -> None:
    with pytest.raises(ValueError):
        funcion([])


def test_curva_sin_predicciones_es_un_error() -> None:
    with pytest.raises(ValueError, match="No hay predicciones"):
        curva_riesgo_cobertura([], [0.5])


# --- carga -------------------------------------------------------------------


def test_cargar_tsv_junta_titulo_y_descripcion(tmp_path) -> None:
    ruta = tmp_path / "prueba.tsv"
    ruta.write_text(
        'categoria\ttitulo\tdescripcion\nBACHES\tPozo en la esquina\tEs "enorme", rompe autos\n',
        encoding="utf-8",
    )

    assert cargar_tsv(ruta) == [('Pozo en la esquina Es "enorme", rompe autos', "BACHES")]
