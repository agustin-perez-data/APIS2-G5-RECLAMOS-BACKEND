"""Multinomial Naive Bayes in pure Python.

Why hand-rolled instead of scikit-learn: the model is small, so is the corpus,
and this keeps numpy/scipy — and a binary artifact that would need versioning
of its own — out of the service image. The interface (`fit` / `predict_proba`)
matches sklearn's, so swapping in a pipeline trained on real data is a
one-class change (see `app/services/clasificador.py`).
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Sequence


class MultinomialNaiveBayes:
    """Bag-of-tokens text classifier with Laplace smoothing."""

    def __init__(self, alpha: float = 1.0, temperatura: float = 1.0) -> None:
        if temperatura <= 0:
            raise ValueError("La temperatura tiene que ser positiva")
        self.alpha = alpha
        # Temperature scaling (Guo et al., 2017). Naive Bayes multiplies many
        # token probabilities as if they were independent, which pushes the
        # posterior towards 0 or 1. Dividing the log-scores by a temperature
        # above 1 softens it without changing which class wins.
        self.temperatura = temperatura
        self.clases: list[str] = []
        self.vocabulario: set[str] = set()
        self._log_prior: dict[str, float] = {}
        self._log_verosimilitud: dict[str, dict[str, float]] = {}
        self._log_desconocido: dict[str, float] = {}

    @property
    def entrenado(self) -> bool:
        return bool(self.clases)

    def fit(self, documentos: Sequence[tuple[Sequence[str], str]]) -> MultinomialNaiveBayes:
        """`documentos` is a sequence of (tokens, label) pairs."""
        if not documentos:
            raise ValueError("El corpus de entrenamiento esta vacio")

        conteo_docs: Counter[str] = Counter()
        conteo_tokens: dict[str, Counter[str]] = defaultdict(Counter)

        for tokens, etiqueta in documentos:
            conteo_docs[etiqueta] += 1
            conteo_tokens[etiqueta].update(tokens)
            self.vocabulario.update(tokens)

        self.clases = sorted(conteo_docs)
        total_docs = sum(conteo_docs.values())
        tamano_vocab = len(self.vocabulario)

        for clase in self.clases:
            self._log_prior[clase] = math.log(conteo_docs[clase] / total_docs)

            total_clase = sum(conteo_tokens[clase].values())
            denominador = total_clase + self.alpha * (tamano_vocab + 1)

            self._log_verosimilitud[clase] = {
                token: math.log((conteo_tokens[clase][token] + self.alpha) / denominador)
                for token in self.vocabulario
            }
            # Fallback probability for tokens outside the vocabulary.
            self._log_desconocido[clase] = math.log(self.alpha / denominador)

        return self

    def _log_scores(self, tokens: Sequence[str]) -> dict[str, float]:
        conocidos = [t for t in tokens if t in self.vocabulario]
        return {
            clase: self._log_prior[clase]
            + sum(self._log_verosimilitud[clase][t] for t in conocidos)
            for clase in self.clases
        }

    def predict_proba(self, tokens: Sequence[str]) -> dict[str, float]:
        """Posterior probability per class, normalised with log-sum-exp."""
        if not self.entrenado:
            raise RuntimeError("El modelo no fue entrenado")

        scores = {
            clase: score / self.temperatura for clase, score in self._log_scores(tokens).items()
        }
        maximo = max(scores.values())
        exponenciales = {clase: math.exp(score - maximo) for clase, score in scores.items()}
        total = sum(exponenciales.values())
        return {clase: valor / total for clase, valor in exponenciales.items()}

    def predict(self, tokens: Sequence[str]) -> tuple[str, float]:
        probabilidades = self.predict_proba(tokens)
        clase = max(probabilidades, key=probabilidades.__getitem__)
        return clase, probabilidades[clase]

    def tokens_decisivos(self, tokens: Sequence[str], clase: str, limite: int = 5) -> list[str]:
        """Tokens that pushed hardest towards `clase`.

        Ranked by log-ratio against the best competing class: a token common to
        every category explains nothing, while one that only shows up here does.
        This is what we surface as `evidencia` so an operator can audit the
        suggestion.
        """
        if clase not in self._log_verosimilitud:
            return []

        otras = [c for c in self.clases if c != clase]
        puntajes: list[tuple[float, str]] = []
        for token in dict.fromkeys(tokens):  # unique, order preserved
            if token not in self.vocabulario:
                continue
            propio = self._log_verosimilitud[clase][token]
            rival = max(self._log_verosimilitud[c][token] for c in otras) if otras else 0.0
            puntajes.append((propio - rival, token))

        puntajes.sort(reverse=True)
        return [token.replace("_", " ") for score, token in puntajes[:limite] if score > 0]


class ComplementNaiveBayes(MultinomialNaiveBayes):
    """Complement Naive Bayes (Rennie et al., 2003).

    Each class is described by the tokens of every OTHER class, and a document
    goes to the class whose complement it resembles least. With few examples
    per class the complement has several times more data than the class
    itself, so the estimates are steadier.

    It reuses the parent's scoring by storing the negated complement
    log-probability as the token weight: higher still means "more this class",
    so `predict_proba` and `tokens_decisivos` work unchanged. The class prior
    is left out, as in the original formulation.
    """

    def fit(self, documentos: Sequence[tuple[Sequence[str], str]]) -> ComplementNaiveBayes:
        if not documentos:
            raise ValueError("El corpus de entrenamiento esta vacio")

        conteo_tokens: dict[str, Counter[str]] = defaultdict(Counter)
        total: Counter[str] = Counter()
        for tokens, etiqueta in documentos:
            conteo_tokens[etiqueta].update(tokens)
            total.update(tokens)
            self.vocabulario.update(tokens)

        self.clases = sorted(conteo_tokens)
        tamano_vocab = len(self.vocabulario)
        total_tokens = sum(total.values())

        for clase in self.clases:
            self._log_prior[clase] = 0.0
            total_complemento = total_tokens - sum(conteo_tokens[clase].values())
            denominador = total_complemento + self.alpha * (tamano_vocab + 1)
            self._log_verosimilitud[clase] = {
                token: -math.log(
                    (total[token] - conteo_tokens[clase][token] + self.alpha) / denominador
                )
                for token in self.vocabulario
            }
            self._log_desconocido[clase] = -math.log(self.alpha / denominador)

        return self
