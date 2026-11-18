"""Export the claims where an operator overruled the classifier (ADR 0019).

Those are the examples worth adding to the corpus: real text, written by a
neighbour, that the model got wrong, with the label of the person who fixed it.

    RECLAMOS_ADMIN_TOKEN=<jwt de un admin> python scripts/exportar_correcciones.py
    ... --formato corpus      # rows ready to paste into app/ml/corpus_ampliado.py
    ... --api http://localhost:8000/api/v1

The token is read from the environment, never from the command line, so it
does not end up in the shell history.

This prints candidates for a person to review. It does not edit the corpus:
a neighbour's text can carry a name or an address, and an operator's
correction can itself be wrong. After adding rows, re-run
`scripts/evaluar_clasificador.py`.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from typing import Any

import httpx

API_POR_DEFECTO = "https://apis2-g5-reclamos-backend.onrender.com/api/v1"
VARIABLE_TOKEN = "RECLAMOS_ADMIN_TOKEN"


def _en_una_linea(texto: str) -> str:
    return " ".join(texto.split())


def texto_de(fila: dict[str, Any]) -> str:
    """Title plus description, as the classifier reads a claim."""
    return _en_una_linea(f"{fila['titulo']} {fila['descripcion']}")


def a_tsv(filas: Sequence[dict[str, Any]]) -> str:
    """One row per correction, for review in a spreadsheet."""
    lineas = ["categoria\tcategoria_sugerida\tconfianza_sugerida\ttitulo\tdescripcion"]
    for fila in filas:
        confianza = fila.get("confianza_sugerida")
        lineas.append(
            "\t".join(
                [
                    fila["categoria"],
                    fila["categoria_sugerida"],
                    "" if confianza is None else f"{confianza:.4f}",
                    _en_una_linea(fila["titulo"]),
                    _en_una_linea(fila["descripcion"]),
                ]
            )
        )
    return "\n".join(lineas) + "\n"


def a_corpus(filas: Sequence[dict[str, Any]]) -> str:
    """Rows in the shape of `_POR_CATEGORIA`, grouped by corrected category."""
    por_categoria: dict[str, list[str]] = {}
    for fila in filas:
        por_categoria.setdefault(fila["categoria"], []).append(texto_de(fila))

    lineas: list[str] = []
    for categoria in sorted(por_categoria):
        lineas.append(f"    CategoriaReclamo.{categoria}: (")
        for texto in por_categoria[categoria]:
            lineas.append(f"        {texto!r},")
        lineas.append("    ),")
    return "\n".join(lineas) + "\n" if lineas else ""


def descargar(api: str, token: str, limite: int) -> list[dict[str, Any]]:
    respuesta = httpx.get(
        f"{api.rstrip('/')}/reclamos/clasificador/correcciones",
        params={"limite": limite},
        headers={"Authorization": f"Bearer {token}"},
        timeout=90,  # the free tier may be asleep
    )
    respuesta.raise_for_status()
    return respuesta.json()


def main(argumentos: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=API_POR_DEFECTO)
    parser.add_argument("--formato", choices=("tsv", "corpus"), default="tsv")
    parser.add_argument("--limite", type=int, default=200)
    opciones = parser.parse_args(argumentos)

    token = os.environ.get(VARIABLE_TOKEN)
    if not token:
        print(f"Falta la variable de entorno {VARIABLE_TOKEN}", file=sys.stderr)
        return 2

    filas = descargar(opciones.api, token, opciones.limite)
    sys.stdout.write(a_tsv(filas) if opciones.formato == "tsv" else a_corpus(filas))
    print(f"{len(filas)} correcciones exportadas", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
