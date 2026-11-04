# ADR 0014 — Modo evento climático

- **Estado:** Aceptada
- **Fecha:** 2026-11-03
- **Contexto:** Caso de uso transversal del squad 3, "Alerta climática" · Grupo 5

## Contexto

Espacios Públicos y Cultura lee una API de clima. Cuando detecta un fenómeno
fuerte, su administrador lo valida, le asigna una gravedad y publica un evento
para todos los módulos. A Reclamos le toca lo que ningún otro módulo puede
hacer: cruzar la zona afectada con los reclamos abiertos, avisarle al vecino que
la gestión puede demorarse, priorizar los reclamos que el clima empeora y, al
terminar, retomar la gestión normal.

**Reclamos no resuelve el reclamo.** La resolución es del grupo dueño de la
categoría. Este módulo es dueño del registro y sólo mueve prioridad, nunca
destino.

### Qué manda Espacios, de verdad

El contrato se leyó del **schema registrado en el catálogo del bus**
(`com.citypass.espacios.CriticidadClimaticaConfirmada`, schemaId 28, 2026-11-03),
no del documento de diseño. Importa porque los dos no coincidían: el documento
decía que no venían los barrios y **sí vienen**.

| Campo | Tipo |
| --- | --- |
| `alertaId` | string |
| `nivelCriticidad` | **enum** `BAJA, MEDIA, ALTA, CRITICA` |
| `fenomeno` | **enum** de 9 símbolos |
| `barrios` | array de string, `default: []` |
| `ubicaciones` | array de `{latitud, longitud}` |
| `vigenciaDesde` / `vigenciaHasta` | long, `timestamp-millis` |
| `temperaturaMinC` / `MaxC` | nullable |
| `actorSub` | string |

**No trae número de versión.** Y la entrega del gateway es *at-least-once*: su
propio README admite que puede haber duplicados.

## Opciones consideradas

### Cómo se calcula el área afectada

#### A. Sólo por geografía, con un radio alrededor de las `ubicaciones`

- ✅ No depende de cómo esté escrito el barrio del reclamo.
- ❌ **El evento trae un punto, no un área.** Didier confirmó que manda una sola
  coordenada y la toma como "la zona afectada", así que cualquier radio es una
  convención nuestra disfrazada de meteorología.
- ❌ Con un radio chico y una tormenta grande se subcuenta sin que nadie lo note.

#### B. Sólo por barrio ✅ (primario)

- ✅ **Espacios ya calculó los barrios afectados.** Saber cuáles son le gana a
  estimar un área desde un punto.
- ✅ El cruce es una comparación contra una columna indexada.
- ❌ El barrio del reclamo es texto libre, escrito por el vecino.

#### C. Por barrio, con la geografía como alternativa ✅ **(elegida)**

- ✅ Usa el mejor dato cuando está, y no se queda sin nada cuando `barrios`
  llega vacío, que su schema permite.
- ❌ Dos caminos que mantener.

### Qué hacer con los duplicados al terminar la alerta

#### A. Cerrarlos automáticamente

- ✅ Deja la bandeja limpia.
- ❌ **Cerrar el reclamo de un vecino porque se parece a otro, sin que nadie lo
  mire, no es una decisión que le toque a este módulo.** El vecino no se entera
  y pierde su trámite.

#### B. Detectarlos y contarlos ✅ **(elegida)**

- ✅ Analítica obtiene su número y ninguna persona pierde su reclamo.
- ❌ El operador sigue teniendo que mirarlos.

## Decisión

**El cruce es primario por barrio normalizado**, con la geografía como
alternativa cuando `barrios` llega vacío. `reclamos.barrio_codigo` guarda el
barrio normalizado y se mantiene solo, con un `@validates` sobre `barrio`: así
los dos no pueden desincronizarse, y el call site que se olvide de normalizar
sería justo el que deja un reclamo afuera de una alerta en silencio.

**Deduplicación persistente por `eventId`** en `eventos_procesados`, escrita
**antes del trabajo y en la misma transacción**. Si el handler falla, el rollback
se la lleva y la reentrega se procesa. Escribirla después convertiría un handler
fallido en un evento que no se puede reintentar nunca.

**El orden sale del timestamp del bus**, porque su evento no trae versión: un
evento más viejo que el último aplicado se descarta, para que una reentrega de
la confirmación no reviva una alerta ya finalizada.

**El umbral reducido de adhesiones (5 en ALTA, 3 en CRITICA) aplica sólo a un
reclamo marcado con una alerta que sigue viva**, nunca al valor global. Bajar el
global cambiaría la regla de la ciudad entera, incluidos los barrios donde no
pasa nada. El reclamo conserva su `alerta_id` después de que la alerta termina
—es historia y Analítica la lee— así que lo que decide es el estado de la alerta.

**La política por nivel:** BAJA y MEDIA marcan y avisan; ALTA y CRITICA además
suben la prioridad, y sólo de las categorías que el clima empeora (ARBOLADO,
AGUA_CLOACAS, ALUMBRADO). Un reclamo de ruidos bajo tormenta se marca y se le
avisa al vecino, pero no cambia de prioridad.

**Analítica recibe conteos, no campos en `ReclamoCreado`.** Se evaluó agregarle
`alertaId` y `motivoPrioridad` a los eventos de cada reclamo; `motivoPrioridad`
se descartó porque habría sido un campo que por diseño siempre viaja nulo en un
contrato que leen otros seis módulos. `alertaId` se mantiene.

**No se pausan los comentarios ciudadanos en CRITICA.** El diseño original lo
pedía para cuidar la carga durante el pico. **Decidido en contra el 2026-11-04**,
con el squad: con el volumen real del módulo no hay carga que cuidar, y
silenciarle una función al vecino justo durante una emergencia es peor que el
problema que evitaría. No es un pendiente: es una decisión tomada.

**Los duplicados se detectan y se cuentan, no se cierran.** El contador es
deliberadamente tosco —mismo barrio y categoría— porque es un número para
Analítica; el chequeo de verdad es `buscar_similares` (ADR 0007).

**La etapa activa se evalúa al crear el reclamo, sin scheduler.** Una alerta
confirmada cuya ventana todavía no abrió no cuenta.

## Consecuencias

### Positivas

- El área sale del dato de quien la calculó, y no de un radio inventado.
- Una reentrega no le avisa dos veces al mismo vecino.
- El dedup y el orden quedan disponibles para cualquier otro evento de control.
- `escalar_por_incidente` y la alerta comparten el cuerpo del escalado.

### Negativas, y conocidas

- **El barrio es texto libre.** Normalizar arregla mayúsculas, tildes y espacios,
  **pero no tipeos**: "Plaermo" nunca va a cruzar con "PALERMO", y no hay
  corrección difusa a propósito, porque un match equivocado es peor que un
  reclamo afuera — nadie se enteraría.
- **Hay reclamos cuyo barrio no cruza, y conviene separar dos casos.** Medido
  sobre los datos reales el 2026-11-03: de 26 reclamos con barrio, 4 no cruzan
  con una alerta de CABA.
  - **Dos son de otra jurisdicción** (`Dock Sud`, `Lomas de Zamora`). **No es un
    defecto: es correcto que no crucen.** Una alerta de CABA no los alcanza, y
    resolver el barrio desde las coordenadas tampoco los recuperaría.
  - **Dos dicen `Centro`**, que no existe como barrio oficial. Ese es el único
    caso real, y queda como **límite conocido**: son 2 de 26.

  Se evaluó resolver el barrio desde las coordenadas del reclamo y **se
  descartó**: es trabajo grande para recuperar dos filas, y no arregla el caso
  de los barrios de provincia, que es la mitad del número.

  Una tabla de alias a mano taparía `Centro` barato, pero **`Centro` no mapea a
  un barrio sino a una zona**: abarca San Nicolás, Monserrat y parte de Retiro.
  Elegir uno sería meter un dato inventado en el cruce, así que tampoco se hizo.

  **El arreglo de fondo es un catálogo de barrios en el formulario**, para que el
  vecino elija en vez de escribir. Queda anotado para después de la entrega.
- **El fallback por radio aproxima un área desde un punto.** Los radios (2, 5 y
  6 km) son convención nuestra y están en configuración. ALTA es 6 km y no 10
  porque un círculo de 10 km ya cubre los 200 km² de CABA y dejaría ALTA y
  CRITICA haciendo lo mismo.
- **`subidosDePrioridad` cuenta los reclamos elegibles**, no los que realmente
  se movieron: uno que ya estaba en CRITICA era elegible y no cambió. Está
  documentado así en el schema para que nadie lo lea como otra cosa.

- **El reclamo sin barrio ni coordenadas no entra en ninguna alerta.** Se cuenta
  aparte y viaja en los eventos de resumen: es la medida de cuánto cuesta el
  campo de texto libre.
