# Ficha del modelo: clasificador de reclamos

Qué es el modelo, para qué sirve, con qué se entrenó, cuánto rinde y dónde no
hay que confiar en él. Los números salen de
[`evaluacion-clasificador.md`](evaluacion-clasificador.md), que se regenera con
un script; las decisiones están en el
[ADR 0019](../adr/0019-evaluacion-del-clasificador.md).

## Identificación

| | |
| --- | --- |
| Nombre | `complement-naive-bayes-corpus-v2` |
| Tipo | Clasificador de texto multiclase (10 categorías) |
| Algoritmo | Complement Naive Bayes (Rennie et al., 2003), con escalado de temperatura |
| Implementación | Python puro, en `app/ml/` y `app/services/clasificador.py` |
| Entrenamiento | En memoria, la primera vez que se usa; no hay archivo de modelo |
| Reemplaza a | `naive-bayes-corpus-v1` (Naive Bayes multinomial, 70 frases) |

## Uso previsto

**Para qué sirve.** Proponer la categoría de un reclamo cuando el vecino no la
eligió, a partir del título y la descripción. Con la categoría, una regla
aparte calcula la prioridad.

**Quién lo usa.** El alta de reclamos (`POST /reclamos`) y la sugerencia previa
(`POST /reclamos/clasificacion`). El operador ve la categoría, la
confianza y las palabras que la explican, y puede corregirla.

**Cómo se decide con su salida.** Si la confianza es menor a 0,65 el reclamo
nace en `EN_REVISION` y lo mira una persona antes de llegar a un área. El
modelo nunca rechaza ni cierra un reclamo.

**Para qué no sirve.**

- No decide la prioridad: eso es una regla explícita, por ser una decisión de
  política pública que tiene que poder auditarse (ADR 0005).
- No detecta el objeto afectado (ciclovía, vereda): lo elige el vecino.
- No está pensado para textos que no sean reclamos urbanos en castellano
  rioplatense.

## Datos

| Conjunto | Tamaño | Qué es | Uso |
| --- | --- | --- | --- |
| Corpus semilla | 70 frases | Escritas por el equipo en el Sprint 1 | Entrenamiento |
| Ampliación | 296 frases | Escritas para la evaluación de noviembre | Entrenamiento |
| Prueba independiente | 100 casos | Título y descripción, 10 por categoría | Medición |
| Prueba real | 28 casos | Textos cargados en producción, etiquetados a mano | Medición |

**Todos los datos de entrenamiento son sintéticos.** Los escribió el equipo
imitando cómo redacta un vecino; no hay reclamos de vecinos reales en el
corpus.

**Criterio de etiquetado.** La categoría dice qué pasó, no dónde. Los casos
frontera se resolvieron así:

| Caso | Categoría | Por qué |
| --- | --- | --- |
| Vereda rota o baldosas flojas | `BACHES` | Es el estado del solado, igual que la calzada |
| Cable eléctrico caído | `SEGURIDAD` | Es un riesgo para las personas, no un problema de luz |
| Semáforo, señalización, estacionamiento | `TRANSITO` | |
| Luminaria dentro de una plaza | `ALUMBRADO` | Gana el servicio que falla sobre el lugar |
| Ramas y hojas sin retirar | `RESIDUOS` | El problema es la recolección, no el árbol |
| Trámites, boletas, la aplicación | `OTROS` | No son problemas en la vía pública |

**Qué se dejó fuera del conjunto real.** De los 38 reclamos de producción se
usaron 28. Se excluyeron 5 generados por sensores (nunca pasan por el
clasificador), 4 con texto sin sentido y 1 que nombraba a una persona. A los
28 se les revisó la etiqueta leyendo el texto, porque 25 de los 38 tenían como
etiqueta la propia salida del modelo; en dos casos la etiqueta revisada difiere
de la que tenía el reclamo.

**Control de fuga.** Ninguna frase de la ampliación tiene el 80 % o más de sus
raíces dentro de un mismo texto de prueba. Se quitaron 34 frases por esa regla
y un test impide que vuelvan a entrar.

## Rendimiento

| Medición | Resultado | IC 95 % |
| --- | --- | --- |
| Prueba independiente, exactitud | 98/100 (98,0 %) | 93,0 % a 99,4 % |
| Prueba independiente, F1 macro | 0,980 | |
| Prueba real, exactitud | 28/28 (100 %) | 87,9 % a 100 % |
| Modelo anterior, prueba independiente | 79/100 (79,0 %), F1 macro 0,782 | 70,0 % a 85,8 % |
| Modelo anterior, prueba real | 24/28 (85,7 %) | 68,5 % a 94,3 % |
| Referencia por palabras clave | 72,0 %, F1 macro 0,713 | |

Mediciones más exigentes, para acotar el optimismo de las anteriores:

| Medición | Resultado | IC 95 % |
| --- | --- | --- |
| Solo el título, sin la descripción | 94/100 (94,0 %) | 87,5 % a 97,2 % |
| Entrenado con la ampliación, probado sobre el corpus semilla | 66/70 (94,3 %) | 86,2 % a 97,8 % |
| Validación cruzada de 5 pliegues, frases sueltas | 270/366 (73,8 %) | 69,0 % a 78,0 % |

**Cómo leerlo.** El rendimiento depende mucho del largo del texto. Con título
y descripción el modelo tiene de dónde agarrarse; con una sola frase corta
acierta bastante menos. El valor esperable en uso real está entre la medición
entre autores y la del conjunto independiente.

**Confianza.** Con temperatura 0,4 el error de calibración esperado es 0,058.
Con el umbral en 0,65, sobre los conjuntos de prueba el 96 % a 98 % de los
reclamos se clasifica sin revisión y entre 0 % y 2 % del total sale mal
clasificado sin que nadie lo mire.

## Limitaciones conocidas

1. **Datos sintéticos.** El modelo nunca vio cómo escribe un vecino de verdad:
   errores de tipeo, textos de una palabra, mezcla de varios problemas en un
   mismo reclamo.
2. **Un mismo autor escribió la ampliación y la prueba independiente.** Por eso
   el 98 % es una cota superior y no una estimación.
3. **Conjunto real chico y con un solo etiquetador.** 28 casos no alcanzan para
   distinguir un 90 % de un 100 %, y no hay medida de acuerdo entre personas.
   Faltan además casos reales de `OTROS`.
4. **Textos cortos.** Con una frase sola la confianza baja y más reclamos van a
   revisión. Es el comportamiento buscado, pero carga a los operadores.
5. **Un reclamo con dos problemas** ("no hay luz y hay un pozo") recibe una
   sola categoría.
6. **Vocabulario fuera del corpus.** Una palabra que el modelo nunca vio no
   aporta nada. Un texto hecho solo de palabras desconocidas cae en `OTROS`
   con confianza 0 y va a revisión.
7. **La prioridad no está evaluada.** Todo lo de esta ficha es sobre la
   categoría.

## Consideraciones de uso responsable

- **Siempre hay una persona en el circuito.** El modelo sugiere; el operador
  puede corregir cualquier reclamo y el vecino puede elegir la categoría él
  mismo. La baja confianza deriva a revisión en lugar de decidir.
- **La sugerencia es explicable.** Cada una lleva las palabras que más pesaron,
  mostradas como las escribió el vecino.
- **Riesgo de trato desigual por forma de escribir.** Un modelo entrenado con
  frases prolijas puede rendir peor con quien escribe poco o con errores, y
  mandar más de esos reclamos a revisión, que es más lenta. No está medido
  porque no hay datos reales para medirlo. Es la razón principal para
  incorporar correcciones reales al corpus.
- **Datos personales.** El corpus y los conjuntos de prueba no tienen nombres
  ni datos de contacto. Las correcciones que se exportan de producción son
  texto de vecinos: las revisa una persona antes de sumarlas, y solo un
  administrador puede bajarlas.

## Vigilancia en producción

| Qué | Dónde | Para qué |
| --- | --- | --- |
| Tasa de corrección | `GET /reclamos/estadisticas`, bloque `clasificador` | Parte de los reclamos clasificados por el modelo a los que un operador les cambió la categoría. Es una cota inferior del error |
| Confusiones | El mismo bloque | Qué categoría propuso el modelo y cuál quedó |
| Casos corregidos | `GET /reclamos/clasificador/correcciones` (admin) | Material para el corpus |
| Piso de calidad | `tests/unit/test_calidad_clasificador.py` | La build falla si el modelo empeora |

La tasa empieza a contar con los reclamos cargados desde la migración 0013: los
anteriores no guardaron la sugerencia original del modelo.

## Cómo mejorarlo

1. Bajar las correcciones: `python scripts/exportar_correcciones.py --formato corpus`.
2. Revisarlas a mano: quitar datos personales y descartar las correcciones
   dudosas.
3. Agregarlas a `app/ml/corpus_ampliado.py`.
4. Correr `python scripts/evaluar_clasificador.py`. El script elige de nuevo la
   variante, la temperatura y el umbral, y regenera el reporte.
5. Si cambió la variante, la temperatura o el umbral, llevar esos valores a
   `ClasificadorNaiveBayes` y a `confianza_minima_clasificador`. Un test falla
   mientras no coincidan.
6. Subir los pisos de `test_calidad_clasificador.py` si el modelo mejoró.

## Referencias

- Rennie, Shih, Teevan y Karger (2003). *Tackling the Poor Assumptions of Naive
  Bayes Text Classifiers*. ICML.
- Guo, Pleiss, Sun y Weinberger (2017). *On Calibration of Modern Neural
  Networks*. ICML. De ahí sale el escalado de temperatura.
- Mitchell et al. (2019). *Model Cards for Model Reporting*. FAT*. Es el
  formato de esta ficha.
- Wilson (1927). *Probable Inference, the Law of Succession, and Statistical
  Inference*. JASA. El intervalo de confianza usado.
