"""Export of the operator's corrections as corpus candidates (ADR 0019)."""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import httpx
import pytest

RAIZ = pathlib.Path(__file__).resolve().parents[2]

FILAS = [
    {
        "categoria": "ESPACIOS_PUBLICOS",
        "categoria_sugerida": "ALUMBRADO",
        "confianza_sugerida": 0.71234,
        "titulo": "Luminaria rota\ten la plaza",
        "descripcion": "Se rompio una\nlampara de la plaza",
    },
    {
        "categoria": "BACHES",
        "categoria_sugerida": "TRANSITO",
        "confianza_sugerida": None,
        "titulo": "Pozo en la esquina",
        "descripcion": 'Le dicen "el crater"',
    },
]


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location(
        "exportar_correcciones", RAIZ / "scripts" / "exportar_correcciones.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


def test_el_tsv_no_se_rompe_con_tabs_ni_saltos_de_linea_en_el_texto(script) -> None:
    lineas = script.a_tsv(FILAS).splitlines()

    assert lineas[0].split("\t") == [
        "categoria",
        "categoria_sugerida",
        "confianza_sugerida",
        "titulo",
        "descripcion",
    ]
    assert lineas[1].split("\t") == [
        "ESPACIOS_PUBLICOS",
        "ALUMBRADO",
        "0.7123",
        "Luminaria rota en la plaza",
        "Se rompio una lampara de la plaza",
    ]
    assert len(lineas) == 3
    # No confidence stored: the column stays empty instead of saying "None".
    assert lineas[2].split("\t")[2] == ""


def test_el_formato_corpus_agrupa_por_categoria_corregida_y_escapa_comillas(script) -> None:
    salida = script.a_corpus(FILAS)

    assert salida.splitlines() == [
        "    CategoriaReclamo.BACHES: (",
        "        'Pozo en la esquina Le dicen \"el crater\"',",
        "    ),",
        "    CategoriaReclamo.ESPACIOS_PUBLICOS: (",
        "        'Luminaria rota en la plaza Se rompio una lampara de la plaza',",
        "    ),",
    ]


def test_sin_correcciones_el_formato_corpus_queda_vacio(script) -> None:
    assert script.a_corpus([]) == ""
    assert script.a_tsv([]).count("\n") == 1  # just the header


def test_sin_token_no_llama_a_la_api(script, monkeypatch, capsys) -> None:
    monkeypatch.delenv(script.VARIABLE_TOKEN, raising=False)
    monkeypatch.setattr(script.httpx, "get", lambda *a, **k: pytest.fail("no debia llamar"))

    assert script.main([]) == 2
    assert script.VARIABLE_TOKEN in capsys.readouterr().err


def test_main_pide_las_correcciones_con_el_token_y_las_imprime(script, monkeypatch, capsys) -> None:
    pedidos = []

    def get_falso(url, *, params, headers, timeout):
        pedidos.append((url, params, headers))
        return httpx.Response(200, json=FILAS, request=httpx.Request("GET", url))

    monkeypatch.setenv(script.VARIABLE_TOKEN, "un-token")
    monkeypatch.setattr(script.httpx, "get", get_falso)

    assert script.main(["--api", "http://api.local/api/v1/", "--limite", "5"]) == 0

    assert pedidos == [
        (
            "http://api.local/api/v1/reclamos/clasificador/correcciones",
            {"limite": 5},
            {"Authorization": "Bearer un-token"},
        )
    ]
    salida = capsys.readouterr()
    assert salida.out == script.a_tsv(FILAS)
    assert "un-token" not in salida.out + salida.err


def test_un_error_de_la_api_se_propaga(script, monkeypatch) -> None:
    def get_falso(url, **_):
        return httpx.Response(403, request=httpx.Request("GET", url))

    monkeypatch.setenv(script.VARIABLE_TOKEN, "un-token")
    monkeypatch.setattr(script.httpx, "get", get_falso)

    with pytest.raises(httpx.HTTPStatusError):
        script.main([])
