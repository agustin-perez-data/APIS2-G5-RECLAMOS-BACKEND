"""Automatic classification of claims (category + priority).

The design is hybrid on purpose:

* **Category** is predicted by a Naive Bayes model trained on the seed corpus.
  That is the part that learns from data.
* **Priority** is resolved by an explicit rule (urgency lexicon + per-category
  baseline severity). It is a public-policy decision: it must be auditable and
  adjustable by ordinance, not the output of an opaque model.

Every suggestion carries its `confianza` and `evidencia` so an operator can
review it and so we can measure later how well the model is doing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Protocol, runtime_checkable

from app.domain.enums import CategoriaReclamo, PrioridadReclamo, escalar
from app.ml.corpus import CORPUS, TERMINOS_ALTOS, TERMINOS_CRITICOS
from app.ml.naive_bayes import MultinomialNaiveBayes
from app.ml.text import contiene_alguno, tokenizar
from app.schemas.reclamo import SugerenciaClasificacion

# Baseline severity per category: how much the problem hurts by its nature,
# regardless of how the claim happens to be worded.
PRIORIDAD_BASE: dict[CategoriaReclamo, PrioridadReclamo] = {
    CategoriaReclamo.SEGURIDAD: PrioridadReclamo.ALTA,
    CategoriaReclamo.AGUA_CLOACAS: PrioridadReclamo.ALTA,
    CategoriaReclamo.ALUMBRADO: PrioridadReclamo.MEDIA,
    CategoriaReclamo.BACHES: PrioridadReclamo.MEDIA,
    CategoriaReclamo.RESIDUOS: PrioridadReclamo.MEDIA,
    CategoriaReclamo.ARBOLADO: PrioridadReclamo.MEDIA,
    CategoriaReclamo.TRANSITO: PrioridadReclamo.MEDIA,
    CategoriaReclamo.RUIDOS: PrioridadReclamo.BAJA,
    CategoriaReclamo.ESPACIOS_PUBLICOS: PrioridadReclamo.BAJA,
    CategoriaReclamo.OTROS: PrioridadReclamo.BAJA,
}


@runtime_checkable
class Clasificador(Protocol):
    """Port: any implementation works as long as it returns a suggestion.

    Moving to a model trained on real data (sklearn, an inference endpoint, an
    LLM) means implementing this protocol and changing `get_clasificador()`.
    Nothing else in the system notices.
    """

    nombre: str

    def clasificar(self, titulo: str, descripcion: str) -> SugerenciaClasificacion: ...


class ClasificadorNaiveBayes:
    """Default implementation: Naive Bayes plus urgency rules."""

    nombre = "naive-bayes-corpus-v1"

    def __init__(self, corpus: list[tuple[str, CategoriaReclamo]] | None = None) -> None:
        datos = corpus if corpus is not None else CORPUS
        # Low alpha: the corpus is small and we want the terms specific to each
        # category to actually carry weight.
        self._modelo = MultinomialNaiveBayes(alpha=0.3).fit(
            [(tokenizar(texto), categoria.value) for texto, categoria in datos]
        )

    def clasificar(self, titulo: str, descripcion: str) -> SugerenciaClasificacion:
        tokens = tokenizar(f"{titulo} {descripcion}")

        if not tokens:
            return SugerenciaClasificacion(
                categoria=CategoriaReclamo.OTROS,
                prioridad=PrioridadReclamo.BAJA,
                confianza=0.0,
                evidencia=[],
                modelo=self.nombre,
            )

        etiqueta, confianza = self._modelo.predict(tokens)
        categoria = CategoriaReclamo(etiqueta)

        prioridad, evidencia_urgencia = self._calcular_prioridad(tokens, categoria)
        evidencia = self._modelo.tokens_decisivos(tokens, etiqueta) + evidencia_urgencia

        return SugerenciaClasificacion(
            categoria=categoria,
            prioridad=prioridad,
            confianza=round(confianza, 4),
            # dict.fromkeys: unique, preserving the relevance ordering.
            evidencia=list(dict.fromkeys(evidencia))[:8],
            modelo=self.nombre,
        )

    def _calcular_prioridad(
        self, tokens: list[str], categoria: CategoriaReclamo
    ) -> tuple[PrioridadReclamo, list[str]]:
        prioridad = PRIORIDAD_BASE.get(categoria, PrioridadReclamo.MEDIA)

        criticos = contiene_alguno(tokens, TERMINOS_CRITICOS)
        if criticos:
            return PrioridadReclamo.CRITICA, [t.replace("_", " ") for t in criticos]

        altos = contiene_alguno(tokens, TERMINOS_ALTOS)
        if altos:
            # `escalar` never lowers the category's baseline priority.
            return escalar(prioridad, PrioridadReclamo.ALTA), [t.replace("_", " ") for t in altos]

        return prioridad, []


@lru_cache
def get_clasificador() -> Clasificador:
    """One instance per process: training the model per request would be absurd."""
    return ClasificadorNaiveBayes()
