"""Text similarity between claims: TF-IDF weighting plus cosine similarity.

Pure Python like the classifier (ADR 0005): no numpy, no model file. It reuses
the classifier's tokenizer and adds a light Spanish stemmer, because short
claims rarely repeat the exact same word form: "apagada" and "apagado", or
"poste" and "postes", have to count as the same term.

IDF is computed over the query plus its candidates. Words every claim nearby
shares ("calle", "esquina") weigh little; the ones only two claims share weigh
a lot, which is what separates "the same broken lamp" from "another lamp".
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

# The stemmer lives with the tokenizer since the classifier started using it
# too; it is re-exported here because this is where it was first introduced.
from app.ml.text import LARGO_MINIMO_RAIZ, raiz, tokenizar

__all__ = ["LARGO_MINIMO_RAIZ", "raiz", "similitudes", "terminos_en_comun", "tokens"]


def tokens(texto: str) -> list[str]:
    """Stemmed unigrams plus bigrams of the stems."""
    return tokenizar(texto, con_raices=True)


def _vector(documento: Sequence[str], idf: dict[str, float]) -> dict[str, float]:
    frecuencias = Counter(documento)
    pesos = {t: c * idf[t] for t, c in frecuencias.items()}
    norma = math.sqrt(sum(p * p for p in pesos.values()))
    return {t: p / norma for t, p in pesos.items()} if norma else {}


def similitudes(consulta: Sequence[str], documentos: Sequence[Sequence[str]]) -> list[float]:
    """Cosine similarity in [0, 1] between the query and each document."""
    if not documentos:
        return []
    corpus = [consulta, *documentos]
    n = len(corpus)
    df = Counter(t for doc in corpus for t in set(doc))
    # Smoothed IDF (as in scikit-learn): never zero, never negative.
    idf = {t: math.log((1 + n) / (1 + d)) + 1 for t, d in df.items()}

    q = _vector(consulta, idf)
    resultado = []
    for documento in documentos:
        v = _vector(documento, idf)
        # Both vectors are normalized, so the dot product is the cosine.
        resultado.append(min(1.0, sum(peso * v.get(t, 0.0) for t, peso in q.items())))
    return resultado


def terminos_en_comun(consulta: str, candidato: str, limite: int = 5) -> list[str]:
    """Candidate words whose stem also shows up in the query, as written.

    Shown to the citizen as the reason for the match, so they come out readable
    ("luminaria", not the stem "luminari").
    """
    raices_consulta = {raiz(p) for p in tokenizar(consulta, con_bigramas=False)}
    vistos: list[str] = []
    for palabra in tokenizar(candidato, con_bigramas=False):
        if raiz(palabra) in raices_consulta and palabra not in vistos:
            vistos.append(palabra)
            if len(vistos) == limite:
                break
    return vistos
