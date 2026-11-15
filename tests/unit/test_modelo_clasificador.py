"""The pieces of the model the evaluation chose (ADR 0019)."""

from __future__ import annotations

import pytest

from app.domain.enums import CategoriaReclamo
from app.ml.naive_bayes import ComplementNaiveBayes, MultinomialNaiveBayes
from app.ml.text import raiz, tokenizar
from app.services.clasificador import ClasificadorNaiveBayes

DOCUMENTOS = [
    (["luz", "apagada", "poste"], "ALUMBRADO"),
    (["farol", "luz", "roto"], "ALUMBRADO"),
    (["pozo", "calle", "asfalto"], "BACHES"),
    (["bache", "calle", "profundo"], "BACHES"),
    (["basura", "contenedor", "olor"], "RESIDUOS"),
]


# --- temperatura -------------------------------------------------------------


@pytest.mark.parametrize("algoritmo", [MultinomialNaiveBayes, ComplementNaiveBayes])
def test_la_temperatura_no_cambia_la_clase_que_gana(algoritmo) -> None:
    tokens = ["luz", "poste", "calle"]
    ganadoras = {
        algoritmo(alpha=1.0, temperatura=t).fit(DOCUMENTOS).predict(tokens)[0]
        for t in (0.2, 1.0, 5.0)
    }

    assert len(ganadoras) == 1


def test_temperatura_baja_afila_y_alta_suaviza() -> None:
    tokens = ["luz", "poste"]

    def confianza(temperatura: float) -> float:
        modelo = ComplementNaiveBayes(alpha=1.0, temperatura=temperatura).fit(DOCUMENTOS)
        return modelo.predict(tokens)[1]

    assert confianza(0.3) > confianza(1.0) > confianza(4.0)


@pytest.mark.parametrize("temperatura", [0.0, -1.0])
def test_una_temperatura_no_positiva_es_un_error(temperatura: float) -> None:
    with pytest.raises(ValueError, match="positiva"):
        MultinomialNaiveBayes(temperatura=temperatura)


# --- Complement Naive Bayes --------------------------------------------------


def test_complement_clasifica_por_lo_que_no_se_parece_a_las_otras_clases() -> None:
    modelo = ComplementNaiveBayes(alpha=1.0).fit(DOCUMENTOS)

    assert modelo.predict(["luz", "farol"])[0] == "ALUMBRADO"
    assert modelo.predict(["pozo", "asfalto"])[0] == "BACHES"
    assert modelo.predict(["basura", "olor"])[0] == "RESIDUOS"


def test_complement_devuelve_una_distribucion() -> None:
    probabilidades = ComplementNaiveBayes(alpha=1.0).fit(DOCUMENTOS).predict_proba(["luz"])

    assert sum(probabilidades.values()) == pytest.approx(1.0)
    assert set(probabilidades) == {"ALUMBRADO", "BACHES", "RESIDUOS"}


def test_complement_explica_con_los_tokens_propios_de_la_clase() -> None:
    modelo = ComplementNaiveBayes(alpha=1.0).fit(DOCUMENTOS)

    # "calle" is all over BACHES; "luz" only shows up in ALUMBRADO.
    assert modelo.tokens_decisivos(["luz", "calle"], "ALUMBRADO") == ["luz"]


def test_complement_no_se_rompe_con_palabras_que_nunca_vio() -> None:
    modelo = ComplementNaiveBayes(alpha=1.0).fit(DOCUMENTOS)

    assert modelo.predict(["zzz", "luz"])[0] == "ALUMBRADO"


def test_complement_con_corpus_vacio_es_un_error() -> None:
    with pytest.raises(ValueError, match="vacio"):
        ComplementNaiveBayes().fit([])


# --- raices ------------------------------------------------------------------


def test_la_raiz_junta_plural_y_genero() -> None:
    assert raiz("apagada") == raiz("apagado") == raiz("apagados")
    assert raiz("postes") == raiz("poste")
    assert raiz("gas") == "gas"  # too short to strip


def test_tokenizar_con_raices_arma_los_bigramas_sobre_las_raices() -> None:
    assert tokenizar("luminarias apagadas", con_raices=True) == [
        "luminari",
        "apagad",
        "luminari_apagad",
    ]


# --- el clasificador ---------------------------------------------------------

CORPUS_CHICO = [
    ("La luminaria esta apagada", CategoriaReclamo.ALUMBRADO),
    ("Farol roto y sin luz", CategoriaReclamo.ALUMBRADO),
    ("Hay un bache profundo en la calzada", CategoriaReclamo.BACHES),
    ("Pozo enorme en el asfalto", CategoriaReclamo.BACHES),
]


def test_la_evidencia_muestra_las_palabras_del_vecino_no_las_raices() -> None:
    clasificador = ClasificadorNaiveBayes(corpus=CORPUS_CHICO)

    sugerencia = clasificador.clasificar("Luminarias apagadas", "Estan todas apagadas")

    assert sugerencia.categoria is CategoriaReclamo.ALUMBRADO
    assert "luminarias" in sugerencia.evidencia
    assert "luminari" not in sugerencia.evidencia


def test_las_raices_reconocen_una_forma_que_no_estaba_en_el_corpus() -> None:
    # The corpus says "apagada"; the claim says "apagados".
    con = ClasificadorNaiveBayes(corpus=CORPUS_CHICO, con_raices=True)
    sin = ClasificadorNaiveBayes(corpus=CORPUS_CHICO, con_raices=False)

    assert con.predecir("apagados")[0] == "ALUMBRADO"
    assert con.predecir("apagados")[1] > sin.predecir("apagados")[1]


def test_la_prioridad_sigue_leyendo_las_palabras_enteras() -> None:
    # The urgency lexicon lists "incendio", not its stem.
    clasificador = ClasificadorNaiveBayes(corpus=CORPUS_CHICO)

    sugerencia = clasificador.clasificar("Incendio en el poste", "Hay fuego en la luminaria")

    assert sugerencia.prioridad.value == "CRITICA"


def test_predecir_un_texto_sin_palabras_utiles() -> None:
    clasificador = ClasificadorNaiveBayes(corpus=CORPUS_CHICO)

    assert clasificador.predecir("de la y") == ("OTROS", 0.0)
    assert clasificador.probabilidades("de la y") == {}


def test_consultar_a_otra_temperatura_no_deja_el_modelo_cambiado() -> None:
    clasificador = ClasificadorNaiveBayes(corpus=CORPUS_CHICO, temperatura=1.0)
    antes = clasificador.predecir("luminaria apagada")

    afilada = clasificador.probabilidades("luminaria apagada", temperatura=0.2)

    assert afilada["ALUMBRADO"] > antes[1]
    assert clasificador.predecir("luminaria apagada") == antes


def test_la_configuracion_por_defecto_es_la_que_eligio_la_evaluacion() -> None:
    clasificador = ClasificadorNaiveBayes(corpus=CORPUS_CHICO)

    assert clasificador.nombre == "complement-naive-bayes-corpus-v2"
    assert isinstance(clasificador._modelo, ComplementNaiveBayes)
    assert clasificador._modelo.alpha == 1.0
    assert clasificador._modelo.temperatura == 0.4
    assert clasificador._con_raices and clasificador._con_bigramas
