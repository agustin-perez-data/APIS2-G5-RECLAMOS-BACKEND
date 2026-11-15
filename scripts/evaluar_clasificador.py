"""Evaluate the claims classifier and write the report (ADR 0019).

    python scripts/evaluar_clasificador.py            # writes docs/ml/evaluacion-clasificador.md
    python scripts/evaluar_clasificador.py --salida - # prints it instead

The protocol, in the order the script follows it:

1. Check that no training sentence is a copy, or a near copy, of a test text.
2. Compare model variants by stratified 5-fold cross-validation over the
   training corpus only. The test sets are not touched here.
3. On the out-of-fold predictions of the winner, fit the temperature and read
   the confidence threshold off the risk/coverage curve.
4. Only then, measure once on the two held-out sets: the independent one and
   the one made of real production texts.

Everything is deterministic: same corpus, same report.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.core.config import settings  # noqa: E402
from app.domain.enums import CategoriaReclamo  # noqa: E402
from app.ml.corpus import CORPUS, CORPUS_SEMILLA  # noqa: E402
from app.ml.corpus_ampliado import AMPLIACION  # noqa: E402
from app.ml.evaluacion import (  # noqa: E402
    Ejemplo,
    Prediccion,
    Predictor,
    Reporte,
    calibracion,
    cargar_tsv,
    curva_riesgo_cobertura,
    elegir_umbral,
    evaluar,
    log_perdida,
    pliegues_estratificados,
    predecir_conjunto,
    validacion_cruzada,
)
from app.ml.text import tokenizar  # noqa: E402
from app.services.clasificador import ClasificadorNaiveBayes  # noqa: E402

PRUEBA_INDEPENDIENTE = RAIZ / "tests" / "datos" / "clasificador" / "prueba_independiente.tsv"
PRUEBA_REAL = RAIZ / "tests" / "datos" / "clasificador" / "prueba_real.tsv"
SALIDA = RAIZ / "docs" / "ml" / "evaluacion-clasificador.md"

PLIEGUES = 5
# A training sentence with this share of its stems inside one test text is a
# near copy of it.
CERCANIA_MAXIMA = 0.8
# Share of all claims we accept to route to the wrong department with no
# human looking at them. The threshold is whatever keeps the risk under this.
RIESGO_MAXIMO = 0.05
# Below 1 sharpens the posterior, above 1 softens it.
TEMPERATURAS = (0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.7, 1.0, 1.5, 2.0, 3.0, 4.0)
UMBRALES = tuple(round(0.20 + 0.05 * i, 2) for i in range(15))

# Reference vocabulary for the keyword baseline: what somebody would write in
# ten minutes without any learning. Stems, matched against stemmed words.
PALABRAS_CLAVE: dict[str, tuple[str, ...]] = {
    "ALUMBRADO": ("luz", "luminari", "farol", "foco", "alumbrad", "lampar", "oscur"),
    "BACHES": ("bach", "pozo", "asfalt", "paviment", "vered", "baldos", "hundimient"),
    "RESIDUOS": ("basur", "contenedor", "residu", "recolector", "escombr", "bols"),
    "ARBOLADO": ("arbol", "ram", "pod", "raic", "past", "tronc"),
    "AGUA_CLOACAS": ("agu", "cloac", "can", "perdid", "sumider", "desagu", "inund"),
    "TRANSITO": ("semafor", "estacionad", "transit", "aut", "cartel", "send", "velocidad"),
    "RUIDOS": ("ruid", "music", "volumen", "alarm", "parlant", "dormir"),
    "ESPACIOS_PUBLICOS": ("plaz", "jueg", "banc", "parqu", "hamac", "cancha"),
    "SEGURIDAD": ("rob", "segurida", "camar", "polici", "patrullaj", "drog", "amenaz"),
    "OTROS": ("tramit", "consult", "bolet", "expedient", "turn", "aplicacion", "informacion"),
}


@dataclass(frozen=True, slots=True)
class Variante:
    nombre: str
    alpha: float
    con_bigramas: bool
    con_raices: bool
    complementario: bool

    def argumentos(self) -> dict[str, float | bool]:
        return {
            "alpha": self.alpha,
            "con_bigramas": self.con_bigramas,
            "con_raices": self.con_raices,
            "complementario": self.complementario,
        }


def variantes() -> list[Variante]:
    """Every combination compared. The first one is the model as it was."""
    lista: list[Variante] = []
    for complementario in (False, True):
        for con_raices in (False, True):
            for con_bigramas in (True, False):
                for alpha in (0.1, 0.3, 1.0):
                    partes = [
                        "CNB" if complementario else "MNB",
                        "raíces" if con_raices else "palabras",
                        "con bigramas" if con_bigramas else "sin bigramas",
                        f"α={alpha}",
                    ]
                    lista.append(
                        Variante(", ".join(partes), alpha, con_bigramas, con_raices, complementario)
                    )
    original = next(
        v
        for v in lista
        if not v.complementario and not v.con_raices and v.con_bigramas and v.alpha == 0.3
    )
    lista.remove(original)
    return [original, *lista]


def solo_titulos(ruta: Path) -> list[Ejemplo]:
    """The same test set with the description dropped: the short, hard case."""
    with ruta.open(encoding="utf-8", newline="") as archivo:
        filas = csv.DictReader(archivo, delimiter="\t", quoting=csv.QUOTE_NONE)
        return [(fila["titulo"], fila["categoria"]) for fila in filas]


def como_ejemplos(corpus: Sequence[tuple[str, CategoriaReclamo]]) -> list[Ejemplo]:
    return [(texto, categoria.value) for texto, categoria in corpus]


def construir(
    ejemplos: Sequence[Ejemplo], variante: Variante, temperatura: float = 1.0
) -> ClasificadorNaiveBayes:
    corpus = [(texto, CategoriaReclamo(etiqueta)) for texto, etiqueta in ejemplos]
    return ClasificadorNaiveBayes(corpus=corpus, temperatura=temperatura, **variante.argumentos())


# --- Leakage guard -----------------------------------------------------------


def _raices(texto: str) -> set[str]:
    return set(tokenizar(texto, con_bigramas=False, con_raices=True))


def cercania(texto: str, pruebas: Sequence[set[str]]) -> float:
    """Share of the sentence's stems found in the test text closest to it."""
    propias = _raices(texto)
    if not propias:
        return 0.0
    return max(len(propias & prueba) / len(propias) for prueba in pruebas)


def copias_cercanas(
    entrenamiento: Sequence[Ejemplo], pruebas: Sequence[Ejemplo]
) -> list[tuple[float, str]]:
    conjuntos = [_raices(texto) for texto, _ in pruebas]
    encontradas = [(cercania(texto, conjuntos), texto) for texto, _ in entrenamiento]
    return sorted((c, t) for c, t in encontradas if c >= CERCANIA_MAXIMA)


# --- Baselines ---------------------------------------------------------------


def predictor_mayoritario(ejemplos: Sequence[Ejemplo]) -> Predictor:
    conteo: dict[str, int] = defaultdict(int)
    for _, etiqueta in ejemplos:
        conteo[etiqueta] += 1
    mayoritaria = max(sorted(conteo), key=conteo.__getitem__)
    return lambda _texto: (mayoritaria, 1.0)


def predictor_palabras_clave(_ejemplos: Sequence[Ejemplo]) -> Predictor:
    def predecir(texto: str) -> tuple[str, float]:
        presentes = _raices(texto)
        puntajes = {
            clase: sum(any(r.startswith(clave) for r in presentes) for clave in claves)
            for clase, claves in PALABRAS_CLAVE.items()
        }
        mejor = max(sorted(puntajes), key=puntajes.__getitem__)
        if puntajes[mejor] == 0:
            return "OTROS", 0.0
        return mejor, puntajes[mejor] / sum(puntajes.values())

    return predecir


# --- Temperature and threshold ----------------------------------------------


def fuera_de_pliegue(
    ejemplos: Sequence[Ejemplo], variante: Variante
) -> list[tuple[str, dict[float, dict[str, float]]]]:
    """For every example, the posterior at each temperature from a model that never saw it."""
    pliegues = pliegues_estratificados([etiqueta for _, etiqueta in ejemplos], PLIEGUES)
    resultado: list[tuple[str, dict[float, dict[str, float]]]] = []
    for pliegue in pliegues:
        afuera = set(pliegue)
        modelo = construir([e for i, e in enumerate(ejemplos) if i not in afuera], variante)
        for indice in pliegue:
            texto, real = ejemplos[indice]
            resultado.append(
                (real, {t: modelo.probabilidades(texto, temperatura=t) for t in TEMPERATURAS})
            )
    return resultado


def predicciones_a(
    posteriores: Sequence[tuple[str, dict[float, dict[str, float]]]], temperatura: float
) -> list[Prediccion]:
    predicciones: list[Prediccion] = []
    for real, por_temperatura in posteriores:
        proba = por_temperatura[temperatura]
        if not proba:
            predicciones.append(Prediccion(real, "OTROS", 0.0))
            continue
        predicha = max(proba, key=proba.__getitem__)
        predicciones.append(Prediccion(real, predicha, proba[predicha]))
    return predicciones


def perdida_a(
    posteriores: Sequence[tuple[str, dict[float, dict[str, float]]]], temperatura: float
) -> float:
    return log_perdida([por_t[temperatura].get(real, 0.0) for real, por_t in posteriores])


# --- Report ------------------------------------------------------------------


def _pct(valor: float) -> str:
    return f"{valor * 100:.1f} %".replace(".", ",")


def _num(valor: float, decimales: int = 3) -> str:
    return f"{valor:.{decimales}f}".replace(".", ",")


def _fila_resumen(nombre: str, r: Reporte) -> str:
    bajo, alto = r.intervalo_exactitud
    return (
        f"| {nombre} | {r.aciertos}/{r.total} | {_pct(r.exactitud)} | "
        f"{_pct(bajo)} a {_pct(alto)} | {_num(r.f1_macro)} |"
    )


def _tabla_por_clase(antes: Reporte, despues: Reporte) -> list[str]:
    lineas = [
        "| Categoría | F1 antes | F1 después | Precisión | Recall | Casos |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for clase in sorted(despues.por_clase):
        d = despues.por_clase[clase]
        a = antes.por_clase.get(clase)
        lineas.append(
            f"| `{clase}` | {_num(a.f1, 2) if a else '-'} | {_num(d.f1, 2)} | "
            f"{_num(d.precision, 2)} | {_num(d.recall, 2)} | {d.soporte} |"
        )
    return lineas


def _matriz(r: Reporte) -> list[str]:
    clases = sorted(r.por_clase)
    abreviadas = [c[:4] for c in clases]
    lineas = [
        "| real \\ predicha | " + " | ".join(abreviadas) + " |",
        "| --- |" + " --- |" * len(clases),
    ]
    for real in clases:
        celdas = []
        for predicha in clases:
            n = r.matriz.get((real, predicha), 0)
            celdas.append(f"**{n}**" if real == predicha and n else str(n) if n else "·")
        lineas.append(f"| `{real}` | " + " | ".join(celdas) + " |")
    return lineas


def generar() -> tuple[str, dict[str, float]]:
    """Run the whole protocol. Returns the report and the headline numbers."""
    entrenamiento = como_ejemplos(CORPUS)
    semilla = como_ejemplos(CORPUS_SEMILLA)
    ampliacion = como_ejemplos(AMPLIACION)
    independiente = cargar_tsv(PRUEBA_INDEPENDIENTE)
    real = cargar_tsv(PRUEBA_REAL)

    # 1. Leakage guard. The seed predates the test sets and was written by
    # other people, so it is reported but only the second batch is enforced.
    copias_ampliacion = copias_cercanas(ampliacion, independiente + real)
    copias_semilla = copias_cercanas(semilla, independiente + real)
    if copias_ampliacion:
        detalle = "\n".join(f"  {c:.2f}  {t}" for c, t in copias_ampliacion)
        raise SystemExit(
            "Hay frases de entrenamiento demasiado parecidas a textos de prueba:\n" + detalle
        )

    # 2. Model selection, by cross-validation over the training corpus.
    candidatas = variantes()
    resultados: list[tuple[Variante, Reporte]] = []
    for variante in candidatas:
        predicciones = validacion_cruzada(
            entrenamiento, lambda ej, v=variante: construir(ej, v).predecir, PLIEGUES
        )
        resultados.append((variante, evaluar(predicciones)))
    original, reporte_original = resultados[0]
    elegida, reporte_elegida = max(resultados, key=lambda par: par[1].f1_macro)

    # 3. Temperature and threshold, on out-of-fold predictions of the winner.
    posteriores = fuera_de_pliegue(entrenamiento, elegida)
    temperatura = min(TEMPERATURAS, key=lambda t: perdida_a(posteriores, t))
    oof_sin = predicciones_a(posteriores, 1.0)
    oof = predicciones_a(posteriores, temperatura)
    ece_sin, _ = calibracion(oof_sin)
    ece_con, tabla_calibracion = calibracion(oof)
    curva = curva_riesgo_cobertura(oof, UMBRALES)
    punto = elegir_umbral(curva, RIESGO_MAXIMO)
    umbral = punto.umbral if punto else UMBRALES[-1]

    # 4. Held-out measurements, once.
    modelo_semilla = construir(semilla, original)
    modelo_final = construir(entrenamiento, elegida, temperatura)
    conjuntos = {"Independiente": independiente, "Real": real}
    antes = {
        n: evaluar(predecir_conjunto(c, modelo_semilla.predecir)) for n, c in conjuntos.items()
    }
    pred_final = {n: predecir_conjunto(c, modelo_final.predecir) for n, c in conjuntos.items()}
    despues = {n: evaluar(p) for n, p in pred_final.items()}
    referencias = {
        "Clase mayoritaria": predictor_mayoritario(entrenamiento),
        "Palabras clave": predictor_palabras_clave(entrenamiento),
    }
    ref = {n: evaluar(predecir_conjunto(independiente, p)) for n, p in referencias.items()}

    # Two harder readings of the same model, to bound how optimistic the
    # independent set is: titles only, and a model trained on batch two alone
    # predicting the seed, which other people wrote.
    titulos = solo_titulos(PRUEBA_INDEPENDIENTE)
    reporte_titulos = evaluar(predecir_conjunto(titulos, modelo_final.predecir))
    modelo_ampliacion = construir(ampliacion, elegida, temperatura)
    reporte_entre_autores = evaluar(predecir_conjunto(semilla, modelo_ampliacion.predecir))

    # Learning curve: seed plus the first n sentences per category of batch two.
    por_categoria: dict[str, list[Ejemplo]] = defaultdict(list)
    for ejemplo in ampliacion:
        por_categoria[ejemplo[1]].append(ejemplo)
    curva_aprendizaje: list[tuple[int, Reporte]] = []
    for agregadas in (0, 8, 16, 24, 40):
        parcial = semilla + [e for lista in por_categoria.values() for e in lista[:agregadas]]
        modelo = construir(parcial, elegida, temperatura)
        curva_aprendizaje.append(
            (len(parcial), evaluar(predecir_conjunto(independiente, modelo.predecir)))
        )

    # ------------------------------------------------------------------ text
    conteo: dict[str, int] = defaultdict(int)
    for _, etiqueta in entrenamiento:
        conteo[etiqueta] += 1
    L: list[str] = []
    L += [
        "# Evaluación del clasificador de reclamos",
        "",
        "> Generado por `scripts/evaluar_clasificador.py`. No editar a mano: se",
        "> regenera corriendo el script y es determinístico.",
        "",
        f"Modelo evaluado: `{ClasificadorNaiveBayes.nombre}`. Metodología y decisiones en el",
        "[ADR 0019](../adr/0019-evaluacion-del-clasificador.md); alcance y límites en la",
        "[ficha del modelo](ficha-del-modelo.md).",
        "",
        "## Resultado",
        "",
        "| Conjunto de prueba | Aciertos | Exactitud | IC 95 % | F1 macro |",
        "| --- | --- | --- | --- | --- |",
    ]
    for nombre in conjuntos:
        L.append(_fila_resumen(f"{nombre}, modelo anterior (corpus semilla)", antes[nombre]))
        L.append(_fila_resumen(f"{nombre}, **modelo actual**", despues[nombre]))
    L += [
        "",
        "El intervalo de confianza es el de Wilson. Con conjuntos de este tamaño es",
        "ancho, y hay que leer cada número junto con su intervalo.",
        "",
        "### Qué tan optimista es ese número",
        "",
        "El conjunto independiente y la ampliación del corpus los escribió la misma persona,",
        "así que comparten estilo. Estas tres mediciones más exigentes acotan el resultado:",
        "",
        "| Medición más exigente | Aciertos | Exactitud | IC 95 % | F1 macro |",
        "| --- | --- | --- | --- | --- |",
        _fila_resumen("Independiente, solo el título (sin la descripción)", reporte_titulos),
        _fila_resumen(
            "Entre autores: entrenado con la ampliación, probado sobre el corpus semilla",
            reporte_entre_autores,
        ),
        _fila_resumen(
            f"Validación cruzada de {PLIEGUES} pliegues sobre el corpus (frases sueltas)",
            reporte_elegida,
        ),
        "",
        "La lectura prudente es que la exactitud real está entre la medición entre autores y",
        "la del conjunto independiente, y que depende del largo del texto: con título y",
        "descripción el modelo tiene más palabras en las que apoyarse.",
        "",
        "Como referencia, sobre el conjunto independiente:",
        "",
        "| Referencia | Exactitud | F1 macro |",
        "| --- | --- | --- |",
    ]
    for nombre, r in ref.items():
        L.append(f"| {nombre} | {_pct(r.exactitud)} | {_num(r.f1_macro)} |")
    L += [
        "",
        "## Datos",
        "",
        "| Conjunto | Ejemplos | Origen | Uso |",
        "| --- | --- | --- | --- |",
        f"| Corpus semilla | {len(semilla)} | Escrito por el equipo en el Sprint 1 "
        "| Entrenamiento |",
        f"| Ampliación | {len(ampliacion)} | Escrito para esta evaluación | Entrenamiento |",
        f"| Prueba independiente | {len(independiente)} | Escrito aparte, 10 por categoría, "
        "con título y descripción | Solo medición final |",
        f"| Prueba real | {len(real)} | Textos cargados en producción, etiquetados a mano "
        "| Solo medición final |",
        "",
        "Ejemplos de entrenamiento por categoría: "
        + ", ".join(f"`{c}` {n}" for c, n in sorted(conteo.items()))
        + ".",
        "",
        "**Control de fuga.** Ninguna frase de la ampliación tiene el "
        f"{int(CERCANIA_MAXIMA * 100)} % o más de sus raíces dentro de un mismo texto de",
        "prueba; el script se niega a correr si aparece una. El corpus semilla es anterior a",
        f"los conjuntos de prueba y lo escribieron otras personas: {len(copias_semilla)} de sus",
        f"{len(semilla)} frases superan ese umbral por coincidencia de vocabulario, y se dejan",
        "porque sacarlas cambiaría la línea base.",
        "",
        "## Selección del modelo",
        "",
        f"Validación cruzada estratificada de {PLIEGUES} pliegues sobre el corpus de",
        "entrenamiento. Los conjuntos de prueba no intervienen en esta etapa.",
        "",
        "| Variante | Exactitud | F1 macro |",
        "| --- | --- | --- |",
    ]
    ordenadas = sorted(resultados, key=lambda par: -par[1].f1_macro)
    for variante, r in ordenadas[:8]:
        marca = " **(elegida)**" if variante == elegida else ""
        marca += " (configuración anterior)" if variante == original else ""
        L.append(f"| {variante.nombre}{marca} | {_pct(r.exactitud)} | {_num(r.f1_macro)} |")
    if original not in [v for v, _ in ordenadas[:8]]:
        L.append(
            f"| {original.nombre} (configuración anterior) | "
            f"{_pct(reporte_original.exactitud)} | {_num(reporte_original.f1_macro)} |"
        )
    peor = ordenadas[-1]
    L += [
        "",
        f"Se compararon {len(resultados)} variantes: Naive Bayes multinomial (MNB) y",
        "complementario (CNB), con palabras o con raíces, con y sin bigramas, y tres valores",
        f"de suavizado. La tabla muestra las ocho mejores; la peor fue «{peor[0].nombre}» con",
        f"F1 macro {_num(peor[1].f1_macro)}.",
        "",
        "## Cuánto aportó ampliar el corpus",
        "",
        "Mismo modelo, entrenado con el corpus semilla más una parte creciente de la",
        "ampliación, medido sobre el conjunto independiente:",
        "",
        "| Ejemplos de entrenamiento | Exactitud | F1 macro |",
        "| --- | --- | --- |",
    ]
    for tamano, r in curva_aprendizaje:
        L.append(f"| {tamano} | {_pct(r.exactitud)} | {_num(r.f1_macro)} |")
    L += [
        "",
        "## Resultado por categoría",
        "",
        "Conjunto independiente. «Antes» es el modelo anterior entrenado con el corpus semilla.",
        "",
        *_tabla_por_clase(antes["Independiente"], despues["Independiente"]),
        "",
        "### Matriz de confusión",
        "",
        "Conjunto independiente, modelo actual. Las columnas llevan las cuatro primeras letras",
        "de cada categoría.",
        "",
        *_matriz(despues["Independiente"]),
        "",
    ]
    confusiones = despues["Independiente"].confusiones(5)
    if confusiones:
        L.append(
            "Errores más frecuentes: "
            + "; ".join(f"`{r}` clasificado como `{p}` ({n})" for r, p, n in confusiones)
            + "."
        )
        L.append("")
    L += [
        "## Calibración de la confianza",
        "",
        "La confianza solo sirve como umbral si significa lo que dice. Se ajustó una",
        "temperatura sobre las predicciones fuera de pliegue, eligiendo la que minimiza la",
        "log-pérdida: por debajo de 1 afila la distribución y por encima la suaviza.",
        "",
        "| | Temperatura | Error de calibración esperado (ECE) |",
        "| --- | --- | --- |",
        f"| Sin ajustar | 1 | {_num(ece_sin)} |",
        f"| Ajustada | {temperatura:g} | {_num(ece_con)} |",
        "",
        "Con la temperatura ajustada, por tramo de confianza:",
        "",
        "| Confianza | Casos | Confianza media | Exactitud real |",
        "| --- | --- | --- | --- |",
    ]
    for tramo in tabla_calibracion:
        L.append(
            f"| {_num(tramo.desde, 1)} a {_num(tramo.hasta, 1)} | {tramo.cantidad} | "
            f"{_num(tramo.confianza_media, 2)} | {_num(tramo.exactitud, 2)} |"
        )
    L += [
        "",
        "## Umbral de revisión humana",
        "",
        "Un reclamo cuya confianza queda por debajo del umbral nace en `EN_REVISION` para que",
        "lo mire una persona. La cobertura es la parte de los reclamos que se clasifica sola;",
        "el riesgo es la parte de **todos** los reclamos que se clasifica sola y mal.",
        "",
        f"Criterio: el umbral más bajo cuyo riesgo no supera el {_pct(RIESGO_MAXIMO)},",
        "medido fuera de pliegue.",
        "",
        "| Umbral | Cobertura | Riesgo | Exactitud de lo aceptado | Revisión innecesaria |",
        "| --- | --- | --- | --- | --- |",
    ]
    for p in curva:
        marca = " **(elegido)**" if p.umbral == umbral else ""
        L.append(
            f"| {_num(p.umbral, 2)}{marca} | {_pct(p.cobertura)} | {_pct(p.riesgo)} | "
            f"{_pct(p.exactitud_aceptados)} | {_pct(p.revision_innecesaria)} |"
        )
    L += [
        "",
        "Comprobación del umbral elegido sobre los conjuntos de prueba, que no participaron",
        "de la elección:",
        "",
        "| Conjunto | Cobertura | Riesgo | Exactitud de lo aceptado |",
        "| --- | --- | --- | --- |",
    ]
    riesgos: dict[str, float] = {}
    for nombre, predicciones in pred_final.items():
        (p,) = curva_riesgo_cobertura(predicciones, [umbral])
        riesgos[nombre] = p.riesgo
        L.append(
            f"| {nombre} | {_pct(p.cobertura)} | {_pct(p.riesgo)} | {_pct(p.exactitud_aceptados)} |"
        )
    L += [
        "",
        f"Umbral en uso (`confianza_minima_clasificador`): {_num(umbral, 2)}.",
        "",
        "## Cómo reproducir",
        "",
        "```bash",
        "python scripts/evaluar_clasificador.py",
        "```",
        "",
        "El piso de calidad se verifica en cada corrida de la suite",
        "(`tests/unit/test_calidad_clasificador.py`).",
        "",
    ]

    numeros = {
        "f1_independiente": despues["Independiente"].f1_macro,
        "exactitud_independiente": despues["Independiente"].exactitud,
        "f1_real": despues["Real"].f1_macro,
        "exactitud_real": despues["Real"].exactitud,
        "f1_cv": reporte_elegida.f1_macro,
        "exactitud_titulos": reporte_titulos.exactitud,
        "exactitud_entre_autores": reporte_entre_autores.exactitud,
        "temperatura": temperatura,
        "umbral": umbral,
        "riesgo_independiente": riesgos["Independiente"],
        "riesgo_real": riesgos["Real"],
        "elegida": elegida.nombre,
        "umbral_configurado": settings.confianza_minima_clasificador,
    }
    return "\n".join(L), numeros


def main(argumentos: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salida", default=str(SALIDA), help="archivo destino, o - para stdout")
    opciones = parser.parse_args(argumentos)

    reporte, numeros = generar()
    if opciones.salida == "-":
        sys.stdout.write(reporte)
    else:
        destino = Path(opciones.salida)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(reporte, encoding="utf-8", newline="\n")
        print(f"Reporte escrito en {destino}")
    for clave, valor in numeros.items():
        print(f"  {clave}: {valor}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
