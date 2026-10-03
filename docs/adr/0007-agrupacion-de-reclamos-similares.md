# ADR 0007 — Agrupación de reclamos similares por sugerencia en línea

- **Estado:** Aceptada
- **Fecha:** 2026-09-23
- **Contexto:** Devolución del profesor · Grupo 5

## Contexto

Varios vecinos reportan el mismo problema: la misma luminaria apagada o el mismo
bache. Hoy la única forma de agruparlos es la **adhesión** ("a mí también me
pasa"), pero depende de que el vecino encuentre solo el reclamo existente antes
de cargar el suyo. En la devolución, el profesor lo dijo así: la agrupación *no
puede depender de que alguien mire 60 reclamos a mano y vea cuál pega con cuál*.
Eso funciona con 50 personas, no con toda la ciudad cargando reclamos.

Las opciones que planteó: agrupar automáticamente con reclamos parecidos, o
mostrarle al vecino la agrupación sugerida y que él confirme.

## Opciones consideradas

### A. Solo la adhesión manual (lo que había)

- ✅ Ya existe y está probada.
- ❌ Es exactamente lo que el profesor señaló que no escala.

### B. Embeddings o un LLM para medir similitud semántica

- ✅ Entiende sinónimos: "luz", "foco" y "luminaria" serían lo mismo.
- ❌ Las mismas objeciones del ADR 0005: un servicio externo en el camino del
  alta, costo por pedido, latencia y resultados no deterministas, que complican
  los tests.
- ❌ Un modelo de embeddings local arrastra dependencias de cientos de MB.

### C. Clustering periódico (DBSCAN o k-means) que asigna un `grupo_id`

- ✅ Agrupa todo el histórico, no solo lo nuevo.
- ❌ Hay que persistir grupos (migración), mantenerlos cuando llegan reclamos
  nuevos y correr un job, y el worker no corre en el deploy.
- ❌ No ayuda en el momento que importa: cuando el vecino está por cargar el
  duplicado.

### D. Sugerencia en línea con filtros más TF-IDF *(elegida)*

Se busca en dos momentos: mientras el vecino completa el formulario
(`POST /reclamos/similares`) y en el detalle de un reclamo ya cargado, para el
operador (`GET /reclamos/{id}/similares`). La agrupación efectiva ocurre cuando
el vecino se suma al reclamo existente, con la adhesión que ya había.

- ✅ Python puro y determinista, como el clasificador. Reutiliza su tokenizador.
- ✅ Sin migración: no hay grupos que mantener.
- ✅ Actúa justo antes de que se cree el duplicado.
- ⚠️ El texto solo no reconoce sinónimos. Lo compensa la cercanía geográfica
  (ver la regla más abajo).

## Decisión

Adoptamos la opción **D**.

**1. Filtros en la base, que descartan casi todo.** Solo se comparan reclamos
de la **misma categoría** (la elegida por el vecino, o la que infiere el
clasificador), **abiertos** (no CERRADO ni RECHAZADO) y **cargados en los últimos
30 días**. Si hay coordenadas, además, dentro de un cuadrado de **300 m**; si no
hay, del **mismo barrio**. El cuadrado se resuelve con comparaciones de rango
comunes, así que funciona igual en PostgreSQL y en SQLite, sin extensiones GIS.

**2. Puntaje sobre la lista corta.** Para cada candidato:

```
texto     = coseno TF-IDF entre los dos textos (título + descripción)
cercania  = 1 - distancia / 300 m
puntaje   = 0,7 · texto + 0,3 · cercania      (sin distancia: puntaje = texto)
```

Se muestran los que superan **0,20**, ordenados de mayor a menor, hasta 5.

La regla que sale de esos números se explica en una frase: **un reclamo de la
misma categoría a menos de 100 m se sugiere aunque esté redactado distinto; más
lejos, también tiene que parecerse en el texto.**

**3. Texto.** Se usa el tokenizador del clasificador (sin *stopwords*, con pares
de palabras), más un *stemmer* liviano para el español: "apagada" y "apagado", o
"poste" y "postes", cuentan como el mismo término. El IDF se calcula sobre la
consulta y sus candidatos: las palabras que tienen todos ("calle", "esquina")
pesan poco, y las que comparten solo dos reclamos pesan mucho.

**4. Respuesta pensada para la UI.** Cada sugerencia trae `terminos_en_comun`
(la razón del match, en palabras legibles), `distancia_metros`, `es_propio` y
`ya_adherido`. Así el front ofrece "sumarte" solo donde puede funcionar: el autor
no puede adherir a su propio reclamo, ni nadie dos veces.

**Calibración.** Con reclamos de prueba sobre una luminaria de Rivadavia y
Medrano: los redactados parecido dan 0,39 y 0,24 de similitud de texto; los que
son otro problema, 0,08 o menos. "Lámpara quemada" da 0,03, y es el caso que
rescata la cercanía. Todos los valores se pueden ajustar en `Settings`
(`similares_*`).

## Consecuencias

**Positivas.** Un vecino que está por cargar un duplicado ve el reclamo existente
y se suma. Eso concentra las adhesiones, que a su vez escalan la prioridad. El
operador ve los duplicados de un reclamo sin recorrer la bandeja.

**Negativas.**
- Sinónimos a más de 100 m no se detectan.
- Si el clasificador infiere mal la categoría, los candidatos de la categoría
  correcta no aparecen.
- El umbral se calibró con pocos ejemplos redactados por el equipo.
- No hay una forma de "fusionar" duplicados que ya se cargaron.

**A revisar.**
1. Un diccionario de sinónimos del dominio (luz / foco / lámpara / luminaria):
   mejora barata del punto más flojo.
2. Que el operador pueda marcar un reclamo como duplicado de otro: cerrarlo y
   pasarle sus adhesiones.
3. Medir cuántas veces el vecino se suma y cuántas carga igual, para recalibrar el
   umbral con datos reales.
