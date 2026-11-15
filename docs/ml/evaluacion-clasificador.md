# Evaluación del clasificador de reclamos

> Generado por `scripts/evaluar_clasificador.py`. No editar a mano: se
> regenera corriendo el script y es determinístico.

Modelo evaluado: `complement-naive-bayes-corpus-v2`. Metodología y decisiones en el
[ADR 0019](../adr/0019-evaluacion-del-clasificador.md); alcance y límites en la
[ficha del modelo](ficha-del-modelo.md).

## Resultado

| Conjunto de prueba | Aciertos | Exactitud | IC 95 % | F1 macro |
| --- | --- | --- | --- | --- |
| Independiente, modelo anterior (corpus semilla) | 79/100 | 79,0 % | 70,0 % a 85,8 % | 0,782 |
| Independiente, **modelo actual** | 98/100 | 98,0 % | 93,0 % a 99,4 % | 0,980 |
| Real, modelo anterior (corpus semilla) | 24/28 | 85,7 % | 68,5 % a 94,3 % | 0,846 |
| Real, **modelo actual** | 28/28 | 100,0 % | 87,9 % a 100,0 % | 1,000 |

El intervalo de confianza es el de Wilson. Con conjuntos de este tamaño es
ancho, y hay que leer cada número junto con su intervalo.

### Qué tan optimista es ese número

El conjunto independiente y la ampliación del corpus los escribió la misma persona,
así que comparten estilo. Estas tres mediciones más exigentes acotan el resultado:

| Medición más exigente | Aciertos | Exactitud | IC 95 % | F1 macro |
| --- | --- | --- | --- | --- |
| Independiente, solo el título (sin la descripción) | 94/100 | 94,0 % | 87,5 % a 97,2 % | 0,940 |
| Entre autores: entrenado con la ampliación, probado sobre el corpus semilla | 66/70 | 94,3 % | 86,2 % a 97,8 % | 0,943 |
| Validación cruzada de 5 pliegues sobre el corpus (frases sueltas) | 270/366 | 73,8 % | 69,0 % a 78,0 % | 0,733 |

La lectura prudente es que la exactitud real está entre la medición entre autores y
la del conjunto independiente, y que depende del largo del texto: con título y
descripción el modelo tiene más palabras en las que apoyarse.

Como referencia, sobre el conjunto independiente:

| Referencia | Exactitud | F1 macro |
| --- | --- | --- |
| Clase mayoritaria | 10,0 % | 0,018 |
| Palabras clave | 72,0 % | 0,713 |

## Datos

| Conjunto | Ejemplos | Origen | Uso |
| --- | --- | --- | --- |
| Corpus semilla | 70 | Escrito por el equipo en el Sprint 1 | Entrenamiento |
| Ampliación | 296 | Escrito para esta evaluación | Entrenamiento |
| Prueba independiente | 100 | Escrito aparte, 10 por categoría, con título y descripción | Solo medición final |
| Prueba real | 28 | Textos cargados en producción, etiquetados a mano | Solo medición final |

Ejemplos de entrenamiento por categoría: `AGUA_CLOACAS` 35, `ALUMBRADO` 39, `ARBOLADO` 37, `BACHES` 40, `ESPACIOS_PUBLICOS` 35, `OTROS` 33, `RESIDUOS` 39, `RUIDOS` 38, `SEGURIDAD` 35, `TRANSITO` 35.

**Control de fuga.** Ninguna frase de la ampliación tiene el 80 % o más de sus raíces dentro de un mismo texto de
prueba; el script se niega a correr si aparece una. El corpus semilla es anterior a
los conjuntos de prueba y lo escribieron otras personas: 7 de sus
70 frases superan ese umbral por coincidencia de vocabulario, y se dejan
porque sacarlas cambiaría la línea base.

## Selección del modelo

Validación cruzada estratificada de 5 pliegues sobre el corpus de
entrenamiento. Los conjuntos de prueba no intervienen en esta etapa.

| Variante | Exactitud | F1 macro |
| --- | --- | --- |
| CNB, raíces, con bigramas, α=1.0 **(elegida)** | 73,8 % | 0,733 |
| CNB, raíces, sin bigramas, α=1.0 | 73,0 % | 0,723 |
| CNB, raíces, con bigramas, α=0.3 | 72,1 % | 0,716 |
| CNB, raíces, sin bigramas, α=0.3 | 72,1 % | 0,716 |
| CNB, raíces, sin bigramas, α=0.1 | 71,6 % | 0,711 |
| CNB, raíces, con bigramas, α=0.1 | 71,3 % | 0,709 |
| CNB, palabras, con bigramas, α=1.0 | 68,3 % | 0,679 |
| CNB, palabras, con bigramas, α=0.3 | 68,3 % | 0,678 |
| MNB, palabras, con bigramas, α=0.3 (configuración anterior) | 63,1 % | 0,631 |

Se compararon 24 variantes: Naive Bayes multinomial (MNB) y
complementario (CNB), con palabras o con raíces, con y sin bigramas, y tres valores
de suavizado. La tabla muestra las ocho mejores; la peor fue «MNB, palabras, sin bigramas, α=1.0» con
F1 macro 0,613.

## Cuánto aportó ampliar el corpus

Mismo modelo, entrenado con el corpus semilla más una parte creciente de la
ampliación, medido sobre el conjunto independiente:

| Ejemplos de entrenamiento | Exactitud | F1 macro |
| --- | --- | --- |
| 70 | 81,0 % | 0,804 |
| 150 | 92,0 % | 0,918 |
| 230 | 92,0 % | 0,919 |
| 310 | 97,0 % | 0,970 |
| 366 | 98,0 % | 0,980 |

## Resultado por categoría

Conjunto independiente. «Antes» es el modelo anterior entrenado con el corpus semilla.

| Categoría | F1 antes | F1 después | Precisión | Recall | Casos |
| --- | --- | --- | --- | --- | --- |
| `AGUA_CLOACAS` | 0,87 | 1,00 | 1,00 | 1,00 | 10 |
| `ALUMBRADO` | 0,82 | 0,95 | 0,91 | 1,00 | 10 |
| `ARBOLADO` | 0,90 | 1,00 | 1,00 | 1,00 | 10 |
| `BACHES` | 0,64 | 1,00 | 1,00 | 1,00 | 10 |
| `ESPACIOS_PUBLICOS` | 0,91 | 1,00 | 1,00 | 1,00 | 10 |
| `OTROS` | 0,89 | 1,00 | 1,00 | 1,00 | 10 |
| `RESIDUOS` | 0,87 | 1,00 | 1,00 | 1,00 | 10 |
| `RUIDOS` | 0,59 | 0,95 | 0,91 | 1,00 | 10 |
| `SEGURIDAD` | 0,59 | 0,95 | 1,00 | 0,90 | 10 |
| `TRANSITO` | 0,75 | 0,95 | 1,00 | 0,90 | 10 |

### Matriz de confusión

Conjunto independiente, modelo actual. Las columnas llevan las cuatro primeras letras
de cada categoría.

| real \ predicha | AGUA | ALUM | ARBO | BACH | ESPA | OTRO | RESI | RUID | SEGU | TRAN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `AGUA_CLOACAS` | **10** | · | · | · | · | · | · | · | · | · |
| `ALUMBRADO` | · | **10** | · | · | · | · | · | · | · | · |
| `ARBOLADO` | · | · | **10** | · | · | · | · | · | · | · |
| `BACHES` | · | · | · | **10** | · | · | · | · | · | · |
| `ESPACIOS_PUBLICOS` | · | · | · | · | **10** | · | · | · | · | · |
| `OTROS` | · | · | · | · | · | **10** | · | · | · | · |
| `RESIDUOS` | · | · | · | · | · | · | **10** | · | · | · |
| `RUIDOS` | · | · | · | · | · | · | · | **10** | · | · |
| `SEGURIDAD` | · | 1 | · | · | · | · | · | · | **9** | · |
| `TRANSITO` | · | · | · | · | · | · | · | 1 | · | **9** |

Errores más frecuentes: `SEGURIDAD` clasificado como `ALUMBRADO` (1); `TRANSITO` clasificado como `RUIDOS` (1).

## Calibración de la confianza

La confianza solo sirve como umbral si significa lo que dice. Se ajustó una
temperatura sobre las predicciones fuera de pliegue, eligiendo la que minimiza la
log-pérdida: por debajo de 1 afila la distribución y por encima la suaviza.

| | Temperatura | Error de calibración esperado (ECE) |
| --- | --- | --- |
| Sin ajustar | 1 | 0,339 |
| Ajustada | 0.4 | 0,058 |

Con la temperatura ajustada, por tramo de confianza:

| Confianza | Casos | Confianza media | Exactitud real |
| --- | --- | --- | --- |
| 0,0 a 0,2 | 16 | 0,15 | 0,19 |
| 0,2 a 0,4 | 70 | 0,32 | 0,49 |
| 0,4 a 0,6 | 54 | 0,50 | 0,54 |
| 0,6 a 0,8 | 57 | 0,70 | 0,79 |
| 0,8 a 1,0 | 169 | 0,95 | 0,94 |

## Umbral de revisión humana

Un reclamo cuya confianza queda por debajo del umbral nace en `EN_REVISION` para que
lo mire una persona. La cobertura es la parte de los reclamos que se clasifica sola;
el riesgo es la parte de **todos** los reclamos que se clasifica sola y mal.

Criterio: el umbral más bajo cuyo riesgo no supera el 5,0 %,
medido fuera de pliegue.

| Umbral | Cobertura | Riesgo | Exactitud de lo aceptado | Revisión innecesaria |
| --- | --- | --- | --- | --- |
| 0,20 | 95,6 % | 22,7 % | 76,3 % | 0,8 % |
| 0,25 | 92,6 % | 20,2 % | 78,2 % | 1,4 % |
| 0,30 | 88,3 % | 17,8 % | 79,9 % | 3,3 % |
| 0,35 | 83,6 % | 15,3 % | 81,7 % | 5,5 % |
| 0,40 | 76,5 % | 12,8 % | 83,2 % | 10,1 % |
| 0,45 | 72,4 % | 9,8 % | 86,4 % | 11,2 % |
| 0,50 | 69,4 % | 9,3 % | 86,6 % | 13,7 % |
| 0,55 | 65,6 % | 7,9 % | 87,9 % | 16,1 % |
| 0,60 | 61,7 % | 6,0 % | 90,3 % | 18,0 % |
| 0,65 **(elegido)** | 57,4 % | 4,9 % | 91,4 % | 21,3 % |
| 0,70 | 53,3 % | 4,4 % | 91,8 % | 24,9 % |
| 0,75 | 50,0 % | 3,3 % | 93,4 % | 27,0 % |
| 0,80 | 46,2 % | 2,7 % | 94,1 % | 30,3 % |
| 0,85 | 42,3 % | 1,6 % | 96,1 % | 33,1 % |
| 0,90 | 36,3 % | 0,5 % | 98,5 % | 38,0 % |

Comprobación del umbral elegido sobre los conjuntos de prueba, que no participaron
de la elección:

| Conjunto | Cobertura | Riesgo | Exactitud de lo aceptado |
| --- | --- | --- | --- |
| Independiente | 98,0 % | 2,0 % | 98,0 % |
| Real | 96,4 % | 0,0 % | 100,0 % |

Umbral en uso (`confianza_minima_clasificador`): 0,65.

## Cómo reproducir

```bash
python scripts/evaluar_clasificador.py
```

El piso de calidad se verifica en cada corrida de la suite
(`tests/unit/test_calidad_clasificador.py`).
