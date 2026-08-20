# ADR 0005 — Clasificación automática: Naive Bayes propio + reglas de prioridad

- **Estado:** Aceptada
- **Fecha:** 2026-08-13
- **Contexto:** Sprint 0 · Grupo 5

## Contexto

La rúbrica exige un componente de IA/ML bien aplicado e integrado
funcionalmente (10 pts). El caso natural del módulo: un vecino escribe un
reclamo en lenguaje libre y el sistema tiene que decidir **a qué área va** y
**qué tan urgente es**, sin obligarlo a navegar un combo de diez categorías.

Restricciones reales: no tenemos datos históricos del municipio (arrancamos de
cero), el equipo tiene que poder correr todo sin GPU ni servicios pagos, y la
imagen del servicio no debería pesar cientos de megas.

## Opciones consideradas

### A. Reglas de keywords y nada más

Un diccionario categoría → lista de palabras.

- ✅ Trivial, explicable al 100%.
- ❌ No aprende: cada término nuevo lo agrega una persona a mano.
- ❌ Difícil de defender como "modelo de IA/ML" ante la rúbrica.

### B. scikit-learn (TF-IDF + LinearSVC / MultinomialNB)

- ✅ Estándar, robusto, con métricas y validación cruzada de fábrica.
- ❌ Arrastra numpy y scipy: la imagen Docker crece varios cientos de MB.
- ❌ El modelo entrenado es un `.joblib` binario que hay que versionar aparte
  (o en git, que es peor) y mantener sincronizado con el código.
- ❌ Sin datos reales, el resultado sería igual de bueno que un Naive Bayes
  entrenado con el mismo corpus chico: la complejidad no compra precisión.

### C. Llamar a un LLM para clasificar

- ✅ Excelente calidad sin corpus, entiende matices.
- ❌ Costo por request y dependencia de un servicio externo en el camino
  crítico del alta de un reclamo.
- ❌ No determinista: complica los tests y la auditabilidad.
- ❌ Latencia de segundos en un endpoint que debería responder en milisegundos.

### D. Naive Bayes multinomial propio + reglas para prioridad *(elegida)*

Híbrido: el modelo aprende la **categoría**, una regla explícita decide la
**prioridad**.

- ✅ Es ML de verdad (pesos aprendidos del corpus), no un diccionario.
- ✅ Python puro: ~60 líneas, sin dependencias, corre igual en cualquier lado.
- ✅ Sin artefacto binario: el modelo se entrena al levantar el proceso.
- ✅ Interfaz `fit`/`predict_proba` igual a la de sklearn: migrar es cambiar una
  clase.
- ⚠️ Naive Bayes es sobreconfiado: las probabilidades no están calibradas.

## Decisión

Adoptamos la opción **D**.

### Por qué híbrido, y no ML también para la prioridad

La prioridad de un reclamo es una **decisión de política pública**: define a
quién atiende primero el municipio. Tiene que poder auditarse, explicarse y
ajustarse por ordenanza. Un modelo entrenado con datos históricos aprendería los
sesgos de esos datos — por ejemplo, priorizar los barrios que históricamente
más reclamaron, que suelen ser los que más recursos ya tienen.

Por eso la prioridad sale de un léxico de urgencia explícito
(`fuga de gas`, `cable caído`, `riesgo de electrocución`…) sobre una criticidad
base por categoría, ambos en `app/ml/corpus.py`, revisables en un PR.

### Implementación

- `app/ml/text.py` — normalización (minúsculas, sin tildes, sin puntuación),
  stopwords del español rioplatense, unigramas + **bigramas** (`fuga_gas` pesa
  mucho más que `fuga` y `gas` sueltos).
- `app/ml/naive_bayes.py` — multinomial con suavizado de Laplace (`alpha=0.3`,
  bajo a propósito porque el corpus es chico), log-sum-exp para normalizar.
- `app/ml/corpus.py` — ~70 reclamos etiquetados a mano, redactados como los
  escribe un vecino.
- `app/services/clasificador.py` — orquesta ambas partes detrás del protocolo
  `Clasificador`.

### Explicabilidad y control humano

Cada sugerencia devuelve `confianza` y `evidencia` (los tokens más
discriminativos según el log-ratio contra la mejor clase rival). Si la confianza
cae por debajo de `CONFIANZA_MINIMA_CLASIFICADOR`, el reclamo entra en
`EN_REVISION` para triage humano en vez de caer en la bandeja del área
equivocada. Además se publica `reclamos.reclamo.clasificado` con la confianza y
el nombre del modelo, para poder medir después qué tan bien anduvo.

## Plan de evolución

1. **Ahora:** corpus semilla, modelo entrenado al arrancar.
2. **Sprint 3-4:** alimentar el corpus con reclamos reales. Los que un operador
   reclasificó a mano son los ejemplos más valiosos: son exactamente los que el
   modelo erró.
3. **Sprint 5+:** con volumen suficiente, evaluar sklearn con validación cruzada
   y comparar contra este baseline. Migrar solo si gana de verdad —
   implementando el protocolo `Clasificador` y cambiando `get_clasificador()`.

## Consecuencias

**Positivas.** Cero dependencias extra, tests deterministas (`pytest` verifica
que cada categoría se predice bien y que "fuga de gas" fuerza `CRITICA`), y una
historia clara que contar en la defensa: qué aprende el modelo, qué decide una
regla, y por qué.

**Negativas.** El corpus semilla es chico y está escrito por nosotros: el modelo
va a andar peor con vocabulario que no anticipamos. Lo mitigan el umbral de
confianza y la revisión humana. Naive Bayes tampoco captura negación
("**no** hay basura"), limitación conocida y asumida para este alcance.
