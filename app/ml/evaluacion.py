"""Evaluation of the claims classifier, in pure Python.

Same constraint as the rest of `app/ml` (ADR 0005): no numpy, no scikit-learn.
The metrics here are the standard ones for multi-class text classification and
are small enough to implement and test by hand.

Nothing in this module runs while serving requests. It is used by
`scripts/evaluar_clasificador.py`, which writes the evaluation report, and by
the quality gate in the test suite (ADR 0019).
"""

from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

SIN_PREDICCIONES = "No hay predicciones para evaluar"

# (text, label)
Ejemplo = tuple[str, str]
# text -> (predicted label, confidence in [0, 1])
Predictor = Callable[[str], tuple[str, float]]
# training examples -> predictor
Entrenador = Callable[[Sequence[Ejemplo]], Predictor]


@dataclass(frozen=True, slots=True)
class Prediccion:
    real: str
    predicha: str
    confianza: float

    @property
    def acierto(self) -> bool:
        return self.real == self.predicha


@dataclass(frozen=True, slots=True)
class MetricasClase:
    precision: float
    recall: float
    f1: float
    soporte: int


@dataclass(frozen=True, slots=True)
class Reporte:
    total: int
    aciertos: int
    exactitud: float
    intervalo_exactitud: tuple[float, float]
    f1_macro: float
    por_clase: dict[str, MetricasClase]
    # (real, predicted) -> count
    matriz: dict[tuple[str, str], int] = field(default_factory=dict)

    def confusiones(self, limite: int = 5) -> list[tuple[str, str, int]]:
        """Most frequent mistakes as (real, predicted, count)."""
        errores = [(r, p, n) for (r, p), n in self.matriz.items() if r != p]
        errores.sort(key=lambda fila: (-fila[2], fila[0], fila[1]))
        return errores[:limite]


@dataclass(frozen=True, slots=True)
class PuntoUmbral:
    """What happens if only predictions at or above `umbral` skip human review."""

    umbral: float
    # Share of all claims that skip review.
    cobertura: float
    # Share of all claims that skip review AND are wrong: the risk we accept.
    riesgo: float
    # Accuracy among the ones that skip review.
    exactitud_aceptados: float
    # Share of all claims that are right but get sent to review anyway.
    revision_innecesaria: float


@dataclass(frozen=True, slots=True)
class TramoCalibracion:
    desde: float
    hasta: float
    cantidad: int
    confianza_media: float
    exactitud: float


def cargar_tsv(ruta: str | Path) -> list[Ejemplo]:
    """Read a test set: a TSV with `categoria`, `titulo` and `descripcion` columns.

    The text handed to the model is title plus description, which is exactly
    what `ClasificadorNaiveBayes.clasificar` receives in production.
    """
    with Path(ruta).open(encoding="utf-8", newline="") as archivo:
        filas = csv.DictReader(archivo, delimiter="\t", quoting=csv.QUOTE_NONE)
        return [
            (f"{fila['titulo']} {fila['descripcion']}".strip(), fila["categoria"]) for fila in filas
        ]


def intervalo_wilson(aciertos: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion.

    Preferred over the normal approximation because the test sets here are
    small, and that one misbehaves near 0 and 1 and with few samples.
    """
    if total == 0:
        return (0.0, 0.0)
    p = aciertos / total
    denominador = 1 + z * z / total
    centro = (p + z * z / (2 * total)) / denominador
    margen = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominador
    return (max(0.0, centro - margen), min(1.0, centro + margen))


def evaluar(predicciones: Sequence[Prediccion]) -> Reporte:
    """Accuracy, per-class precision/recall/F1, macro F1 and confusion matrix.

    Macro F1 is the headline number: it weighs every category the same, so a
    model that ignores a rare category cannot hide behind the frequent ones.
    """
    if not predicciones:
        raise ValueError(SIN_PREDICCIONES)

    matriz: Counter[tuple[str, str]] = Counter((p.real, p.predicha) for p in predicciones)
    clases = sorted({p.real for p in predicciones})

    por_clase: dict[str, MetricasClase] = {}
    for clase in clases:
        verdaderos = matriz[(clase, clase)]
        predichos = sum(n for (_, pred), n in matriz.items() if pred == clase)
        reales = sum(n for (real, _), n in matriz.items() if real == clase)
        precision = verdaderos / predichos if predichos else 0.0
        recall = verdaderos / reales if reales else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        por_clase[clase] = MetricasClase(precision, recall, f1, reales)

    total = len(predicciones)
    aciertos = sum(p.acierto for p in predicciones)
    return Reporte(
        total=total,
        aciertos=aciertos,
        exactitud=aciertos / total,
        intervalo_exactitud=intervalo_wilson(aciertos, total),
        f1_macro=sum(m.f1 for m in por_clase.values()) / len(por_clase),
        por_clase=por_clase,
        matriz=dict(matriz),
    )


def pliegues_estratificados(etiquetas: Sequence[str], k: int) -> list[list[int]]:
    """Split indices into `k` folds keeping each class's share in every fold.

    Deterministic on purpose (no shuffling): the same corpus always produces
    the same folds, so two runs of the report are comparable and the quality
    gate cannot flake.
    """
    if k < 2:
        raise ValueError("Hacen falta al menos 2 pliegues")
    por_clase: dict[str, list[int]] = defaultdict(list)
    for indice, etiqueta in enumerate(etiquetas):
        por_clase[etiqueta].append(indice)

    pliegues: list[list[int]] = [[] for _ in range(k)]
    for clase in sorted(por_clase):
        for posicion, indice in enumerate(por_clase[clase]):
            pliegues[posicion % k].append(indice)
    return [sorted(pliegue) for pliegue in pliegues if pliegue]


def validacion_cruzada(
    ejemplos: Sequence[Ejemplo], entrenar: Entrenador, k: int = 5
) -> list[Prediccion]:
    """Out-of-fold predictions: every example is predicted by a model that never saw it."""
    pliegues = pliegues_estratificados([etiqueta for _, etiqueta in ejemplos], k)
    predicciones: list[Prediccion] = []
    for pliegue in pliegues:
        afuera = set(pliegue)
        entrenamiento = [e for i, e in enumerate(ejemplos) if i not in afuera]
        predecir = entrenar(entrenamiento)
        for indice in pliegue:
            texto, real = ejemplos[indice]
            predicha, confianza = predecir(texto)
            predicciones.append(Prediccion(real, predicha, confianza))
    return predicciones


def predecir_conjunto(ejemplos: Sequence[Ejemplo], predecir: Predictor) -> list[Prediccion]:
    """Predictions of an already trained model over a held-out set."""
    return [Prediccion(real, *predecir(texto)) for texto, real in ejemplos]


def curva_riesgo_cobertura(
    predicciones: Sequence[Prediccion], umbrales: Sequence[float]
) -> list[PuntoUmbral]:
    """Trade-off behind `confianza_minima_clasificador`.

    A claim whose confidence is below the threshold is sent to human triage.
    Raising the threshold lowers the risk (wrong claims that slip through) and
    lowers the coverage (claims handled without a person).
    """
    total = len(predicciones)
    if total == 0:
        raise ValueError(SIN_PREDICCIONES)

    puntos: list[PuntoUmbral] = []
    for umbral in umbrales:
        aceptados = [p for p in predicciones if p.confianza >= umbral]
        aceptados_ok = sum(p.acierto for p in aceptados)
        rechazados_ok = sum(p.acierto for p in predicciones if p.confianza < umbral)
        puntos.append(
            PuntoUmbral(
                umbral=umbral,
                cobertura=len(aceptados) / total,
                riesgo=(len(aceptados) - aceptados_ok) / total,
                exactitud_aceptados=aceptados_ok / len(aceptados) if aceptados else 0.0,
                revision_innecesaria=rechazados_ok / total,
            )
        )
    return puntos


def elegir_umbral(puntos: Sequence[PuntoUmbral], riesgo_maximo: float) -> PuntoUmbral | None:
    """Lowest threshold whose risk stays within `riesgo_maximo`.

    The lowest one that qualifies is also the one with the highest coverage,
    because coverage can only fall as the threshold rises.
    """
    candidatos = [p for p in puntos if p.riesgo <= riesgo_maximo]
    return min(candidatos, key=lambda p: p.umbral) if candidatos else None


def calibracion(
    predicciones: Sequence[Prediccion], tramos: int = 5
) -> tuple[float, list[TramoCalibracion]]:
    """Expected calibration error and the reliability table behind it.

    A calibrated model that says 0.7 is right 70% of the time. The threshold
    only means what it says if the confidence is calibrated.
    """
    if not predicciones:
        raise ValueError(SIN_PREDICCIONES)

    grupos: list[list[Prediccion]] = [[] for _ in range(tramos)]
    for p in predicciones:
        indice = min(int(p.confianza * tramos), tramos - 1)
        grupos[indice].append(p)

    total = len(predicciones)
    tabla: list[TramoCalibracion] = []
    ece = 0.0
    for indice, grupo in enumerate(grupos):
        if not grupo:
            continue
        confianza_media = sum(p.confianza for p in grupo) / len(grupo)
        exactitud = sum(p.acierto for p in grupo) / len(grupo)
        ece += len(grupo) / total * abs(confianza_media - exactitud)
        tabla.append(
            TramoCalibracion(
                desde=indice / tramos,
                hasta=(indice + 1) / tramos,
                cantidad=len(grupo),
                confianza_media=confianza_media,
                exactitud=exactitud,
            )
        )
    return ece, tabla


def log_perdida(probabilidades_del_real: Sequence[float]) -> float:
    """Mean negative log-likelihood of the true class (lower is better)."""
    if not probabilidades_del_real:
        raise ValueError("No hay probabilidades para evaluar")
    piso = 1e-12
    return -sum(math.log(max(p, piso)) for p in probabilidades_del_real) / len(
        probabilidades_del_real
    )
