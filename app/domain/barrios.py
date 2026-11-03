"""Comparing a neighbourhood a neighbour typed against one another module sent.

`reclamos.barrio` is free text: the neighbour writes it. Public Spaces sends the
affected ones as a list of codes. "Palermo", "palermo" and "PALERMO" are the same
place and three different strings, so neither side can be compared raw.

Normalising fixes case, accents and stray whitespace. **It does not fix typos**:
"Plaermo" will never match "PALERMO", and there is no silent correction here on
purpose -- a fuzzy match that quietly decides two neighbourhoods are the same is
worse than a claim left out, because nobody would ever find out.

Pure functions, no database and no I/O: the normalised value is stored in
`reclamos.barrio_codigo` so queries filter on an indexed column instead of
normalising every row on every read.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

# Ñ is a letter here, not an accented N: "Ñuñoa" must not collapse into "NUNOA".
_SE_CONSERVAN = {"Ñ", "ñ"}


def normalizar_barrio(texto: str | None) -> str | None:
    """`"  Villa Crespo "` -> `"VILLA CRESPO"`. `None` when there is nothing to compare."""
    if texto is None:
        return None

    # Collapse any run of whitespace, including the newlines a paste can bring in.
    limpio = " ".join(texto.split())
    if not limpio:
        return None

    # Compose first: the same Ñ can arrive as one character or as "N" plus a
    # combining tilde, and only the composed form can be told apart below.
    compuesto = unicodedata.normalize("NFC", limpio)

    # Character by character, because decomposing the whole string first would
    # turn the Ñ into "N" + a combining mark indistinguishable from an accent.
    sin_tildes = []
    for caracter in compuesto:
        if caracter in _SE_CONSERVAN:
            sin_tildes.append(caracter)
            continue
        descompuesto = unicodedata.normalize("NFD", caracter)
        sin_tildes.append("".join(c for c in descompuesto if unicodedata.category(c) != "Mn"))

    return "".join(sin_tildes).upper()


def barrio_afectado(barrio_reclamo: str | None, barrios_alerta: Iterable[str]) -> bool:
    """Whether the claim's neighbourhood is among the alert's.

    Both sides are normalised: the claim's because the neighbour typed it, and
    the alert's because it comes from another module and we do not control how
    they write it either.
    """
    codigo = normalizar_barrio(barrio_reclamo)
    if codigo is None:
        return False

    return codigo in {
        normalizado for barrio in barrios_alerta if (normalizado := normalizar_barrio(barrio))
    }
