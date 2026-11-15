"""Automatic classification of claims (category + priority).

The design is hybrid on purpose:

* **Category** is predicted by a Complement Naive Bayes model trained on the
  corpus in `app/ml/`. That is the part that learns from data. Its
  configuration was chosen by cross-validation and its quality is measured in
  `docs/ml/evaluacion-clasificador.md` (ADR 0019).
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
from app.ml.naive_bayes import ComplementNaiveBayes, MultinomialNaiveBayes
from app.ml.text import contiene_alguno, normalizar, raiz, tokenizar
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
    """Default implementation: Complement Naive Bayes plus urgency rules."""

    nombre = "complement-naive-bayes-corpus-v2"

    def __init__(
        self,
        corpus: list[tuple[str, CategoriaReclamo]] | None = None,
        *,
        alpha: float = 1.0,
        con_bigramas: bool = True,
        con_raices: bool = True,
        complementario: bool = True,
        temperatura: float = 0.4,
    ) -> None:
        """The keyword arguments are the knobs the evaluation compares.

        The defaults are the configuration in production; the report in
        `docs/ml/` records why each one has the value it has (ADR 0019).
        """
        datos = corpus if corpus is not None else CORPUS
        self._con_bigramas = con_bigramas
        self._con_raices = con_raices
        algoritmo = ComplementNaiveBayes if complementario else MultinomialNaiveBayes
        self._modelo = algoritmo(alpha=alpha, temperatura=temperatura).fit(
            [(self._tokens_del_modelo(texto), categoria.value) for texto, categoria in datos]
        )

    def _tokens_del_modelo(self, texto: str) -> list[str]:
        return tokenizar(texto, con_bigramas=self._con_bigramas, con_raices=self._con_raices)

    def predecir(self, texto: str) -> tuple[str, float]:
        """Category and confidence only: what the evaluation needs."""
        tokens = self._tokens_del_modelo(texto)
        if not tokens:
            return CategoriaReclamo.OTROS.value, 0.0
        return self._modelo.predict(tokens)

    def probabilidades(self, texto: str, *, temperatura: float | None = None) -> dict[str, float]:
        """Posterior per category, optionally at another temperature.

        Changing the temperature does not need retraining, which is what lets
        the evaluation fit it on out-of-fold predictions.
        """
        tokens = self._tokens_del_modelo(texto)
        if not tokens:
            return {}
        original = self._modelo.temperatura
        if temperatura is not None:
            self._modelo.temperatura = temperatura
        try:
            return self._modelo.predict_proba(tokens)
        finally:
            self._modelo.temperatura = original

    def clasificar(self, titulo: str, descripcion: str) -> SugerenciaClasificacion:
        texto = f"{titulo} {descripcion}"
        # The urgency lexicon is written with plain words, so priority always
        # reads the unstemmed tokens, whatever the model itself is fed.
        tokens = tokenizar(texto)
        tokens_modelo = self._tokens_del_modelo(texto)

        if not tokens_modelo:
            return SugerenciaClasificacion(
                categoria=CategoriaReclamo.OTROS,
                prioridad=PrioridadReclamo.BAJA,
                confianza=0.0,
                evidencia=[],
                modelo=self.nombre,
            )

        etiqueta, confianza = self._modelo.predict(tokens_modelo)
        categoria = CategoriaReclamo(etiqueta)

        prioridad, evidencia_urgencia = self._calcular_prioridad(tokens, categoria)
        decisivos = self._modelo.tokens_decisivos(tokens_modelo, etiqueta)
        evidencia = self._legibles(decisivos, texto) + evidencia_urgencia

        return SugerenciaClasificacion(
            categoria=categoria,
            prioridad=prioridad,
            confianza=round(confianza, 4),
            # dict.fromkeys: unique, preserving the relevance ordering.
            evidencia=list(dict.fromkeys(evidencia))[:8],
            modelo=self.nombre,
        )

    def _legibles(self, decisivos: list[str], texto: str) -> list[str]:
        """Show the operator the words the neighbour wrote, not their stems."""
        if not self._con_raices:
            return decisivos
        originales: dict[str, str] = {}
        for palabra in normalizar(texto).split():
            originales.setdefault(raiz(palabra), palabra)
        return [
            " ".join(originales.get(parte, parte) for parte in decisivo.split())
            for decisivo in decisivos
        ]

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
