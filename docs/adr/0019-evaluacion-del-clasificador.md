# ADR 0019 — El clasificador se evalúa, se elige y se vigila con datos

- **Estado:** Aceptada
- **Fecha:** 2026-11-15
- **Contexto:** G5D-8 · IA / ML / I+D · Grupo 5
- **Completa:** el [ADR 0005](0005-clasificacion-automatica.md), que eligió
  Naive Bayes en Python puro y dejó para más adelante medir qué tan bien anda.
  La decisión de fondo del 0005 (modelo propio, sin dependencias, prioridad por
  regla) sigue vigente; cambia el algoritmo dentro de esa misma familia.

## Contexto

El clasificador llevaba dos meses en producción sin una sola medición. No
había conjunto de prueba, ni métrica, ni forma de saber si un cambio lo
mejoraba o lo empeoraba. Tres síntomas concretos:

1. **El umbral de revisión humana (`0,35`) no salía de ningún dato.** Es el
   número que decide si un reclamo va directo a un área o lo mira antes una
   persona.
2. **El corpus tenía 7 ejemplos por categoría.** La validación cruzada dejando
   uno afuera daba 28,6 % de exactitud contra 100 % sobre el propio corpus: el
   modelo lo memorizaba.
3. **No se podía medir en producción.** Al reclasificar, el sistema pisaba el
   origen y la confianza, así que no quedaba rastro de qué había sugerido el
   modelo. Y 25 de los 38 reclamos reales tenían como etiqueta la propia salida
   del modelo: usarlos como verdad habría sido circular.

Restricción que se mantiene del ADR 0005: sin numpy ni scikit-learn en la
imagen del servicio.

## Opciones consideradas

### Sobre cómo medir

**A. Validación cruzada sobre el corpus y nada más.** ❌
Es lo más barato, pero el corpus son frases sueltas y en producción entra
título más descripción. Mide otra cosa que lo que el modelo hace de verdad, y
no deja ningún dato fuera de todo el proceso de ajuste.

**B. Un único conjunto de prueba apartado.** ❌
Mejor, pero si se usa también para elegir la variante y el umbral deja de ser
una medición honesta: se termina eligiendo lo que le va bien a ese conjunto.

**C. Validación cruzada para decidir, conjuntos apartados solo para medir.** ✅
La validación cruzada sobre el corpus elige la variante, la temperatura y el
umbral. Dos conjuntos que no participan de ninguna decisión miden el resultado
una sola vez: uno escrito aparte con título y descripción (100 casos, 10 por
categoría) y otro con textos reales de producción etiquetados a mano (28).

### Sobre qué modelo usar

**D. Dejar el Naive Bayes multinomial y solo ampliar el corpus.** ❌
Se midió: con el mismo corpus ampliado queda en F1 macro 0,631 en validación
cruzada, contra 0,733 de la variante elegida.

**E. Traer scikit-learn (regresión logística, SVM lineal).** ❌
Probablemente rinda algo más, pero revierte el ADR 0005 por una mejora que con
este volumen de datos no está demostrada, y suma numpy y scipy a la imagen.

**F. Complement Naive Bayes con raíces, elegido por validación cruzada.** ✅
Se compararon 24 variantes (multinomial o complementario, palabras o raíces,
con o sin bigramas, tres suavizados). Las seis mejores son todas Complement
Naive Bayes con raíces. Sigue siendo Python puro y la misma interfaz.

### Sobre el umbral

**G. Dejar 0,35.** ❌ No tenía respaldo, y con el modelo nuevo la confianza
tiene otra escala.

**H. Elegir el umbral que maximiza la exactitud.** ❌ Optimiza lo que no
importa: lo que cuesta es el reclamo que se va mal clasificado sin que nadie lo
mire, no el que se manda a revisar de más.

**I. Fijar un riesgo máximo y leer el umbral de la curva.** ✅
El riesgo es la parte de todos los reclamos que se clasifica sola y mal. Se
fija en 5 % y se toma el umbral más bajo que lo cumple, que es también el de
mayor cobertura.

## Decisión

1. **Protocolo de evaluación** (`scripts/evaluar_clasificador.py`): control de
   fuga, selección por validación cruzada estratificada de 5 pliegues, ajuste
   de temperatura y umbral sobre predicciones fuera de pliegue, y medición
   final sobre los dos conjuntos apartados. Es determinístico y escribe
   [`docs/ml/evaluacion-clasificador.md`](../ml/evaluacion-clasificador.md).

2. **Modelo en producción:** Complement Naive Bayes, raíces, bigramas, α = 1,
   temperatura 0,4, entrenado con 366 frases. Se identifica como
   `complement-naive-bayes-corpus-v2`.

3. **Temperatura 0,4.** La confianza del modelo sin ajustar quedaba muy por
   debajo de su exactitud real (decía 0,29 y acertaba el 70 %). Con la
   temperatura ajustada el error de calibración esperado baja de 0,339 a 0,058.
   Es lo que permite que el umbral signifique lo que dice.

4. **Umbral `confianza_minima_clasificador = 0,65`**, leído de la curva con
   riesgo máximo de 5 %.

5. **Piso de calidad en la suite** (`tests/unit/test_calidad_clasificador.py`):
   la build falla si el modelo baja de su piso, si el reporte versionado queda
   desactualizado, si lo que está en producción no es lo que eligió la
   evaluación, o si una frase de entrenamiento copia un texto de prueba.

6. **Medición en producción.** El reclamo guarda `categoria_sugerida`,
   `confianza_sugerida` y `modelo_clasificador`, que una reclasificación no
   pisa (migración 0013). `/reclamos/estadisticas` informa la tasa de
   corrección y `/reclamos/clasificador/correcciones` devuelve esos casos como
   candidatos para el corpus.

7. **`origen_clasificacion` describe quién eligió la categoría.** Si la eligió
   el vecino y solo faltaba la prioridad, el origen es `CIUDADANO`, no
   `MODELO`, y la confianza del modelo no decide el estado.

## Consecuencias

**Positivas**

- Hay un número y un intervalo donde antes había una suposición. Sobre el
  conjunto independiente el F1 macro pasó de 0,782 a 0,980, y sobre los textos
  reales la exactitud pasó de 24/28 a 28/28.
- Las categorías que estaban peor son las que más mejoraron: `BACHES` de 0,64
  a 1,00 y `RUIDOS` y `SEGURIDAD` de 0,59 a 0,95.
- Un cambio al corpus o al modelo que lo empeore rompe la build.
- Queda cerrado el ciclo que el corpus prometía desde el Sprint 1: los errores
  que corrige un operador se pueden exportar y volver al entrenamiento.
- `origenClasificacion` deja de contar como del modelo lo que eligió el vecino,
  que es un dato que Analítica consume.

**Negativas**

- **El corpus sigue siendo sintético.** Lo escribió el equipo; no son reclamos
  de vecinos reales.
- **El conjunto independiente y la ampliación del corpus los escribió la misma
  persona**, así que comparten estilo y el 98 % es optimista. Por eso el
  reporte incluye tres mediciones más exigentes: solo el título (94 %),
  entrenar con la ampliación y probar sobre el corpus semilla, que escribieron
  otras personas (94,3 %), y la validación cruzada sobre frases sueltas
  (73,8 %). La lectura prudente está entre esas cifras.
- **El conjunto real es chico (28) y lo etiquetó una sola persona.** Su
  intervalo de confianza va de 87,9 % a 100 %.
- **La tasa de corrección es una cota inferior del error.** Un reclamo mal
  clasificado que nadie revisó no figura como corregido.
- El umbral y la temperatura valen para este modelo: reentrenar obliga a
  volver a leerlos. El test que compara producción contra la evaluación lo
  hace cumplir.
- El umbral más alto manda más reclamos a revisión cuando el texto es muy
  corto: fuera de pliegue, sobre frases sueltas, la cobertura es de 57 %. Con
  título y descripción es de 96 % a 98 %.

**Qué queda por revisar**

1. Conseguir un conjunto de prueba escrito por personas que no hayan visto el
   corpus. Es la única forma de quitar la reserva sobre el 98 %.
2. Cuando haya correcciones de operadores en volumen, incorporarlas al corpus
   y volver a evaluar. Hasta entonces la tasa de corrección parte de cero: los
   reclamos anteriores a la migración 0013 no guardaron su sugerencia.
3. Un segundo etiquetador para el conjunto real, para medir el acuerdo.
4. La regla de prioridad sigue sin evaluarse: este ADR mide solo la categoría.
