# ADR 0017 — Incidentes viales de Emergencias como causa de un reclamo

- **Estado:** Aceptada
- **Fecha:** 2026-11-06
- **Contexto:** G5D-458 · Caso de uso transversal · Grupo 5
- **Completa:** el valor `INCIDENTE_VIAL` que el
  [ADR 0016](0016-causa-del-reclamo-para-analitica.md) declaró en el contrato y
  dejó viajando siempre nulo.

## Contexto

El `CONTRATO_RECLAMOS.md` de Analítica pide `causaId` / `causaTipo` en
`ReclamoCreado`, y de los cuatro valores nos dijeron que **`INCIDENTE_VIAL` es el
que más les importa**: la métrica 4 cuenta reclamos asociados a incidentes viales.

El ADR 0016 declaró el valor y no lo llenó, por dos razones que eran ciertas
entonces:

1. **No guardábamos los incidentes.** `manejar_incidente_creado` escalaba la
   prioridad de los reclamos abiertos del barrio y no dejaba rastro: el
   `incidente_id` quedaba únicamente dentro del texto del `motivo` del historial.
2. **No sabíamos cuándo un incidente dejaba de estar activo.** Sin evento de
   cierre, relacionar reclamos nuevos con un incidente obligaba a inventar una
   vigencia fija, que es una decisión de negocio y no técnica.

El 6/11, revisando el catálogo del bus, apareció que **`com.citypass.emergencias.
EmergenciaActualizada` sí existe** y trae `estadoAnterior`, `estadoNuevo`,
`resueltoAt` y `resolucion`. El segundo motivo dejó de ser cierto.

El contrato de Analítica nombra el evento origen como
`movilidad.IncidenteVialCreado`, que **no existe en el bus**: no hay ningún tipo
con "incidente" ni "vial" en los 62 registrados. La fuente real es
`com.citypass.emergencias.EmergenciaCreada`, que ya consumimos y que trae
`afectaCirculacion`, `estado`, `categoria`, `prioridad` y ubicación.

## Opciones consideradas

**A. No implementarlo y que `INCIDENTE_VIAL` quede nulo.** ❌
Es lo que Analítica dijo que más necesita, y la fuente existe. Dejarlo nulo sin
decirlo convierte una métrica en un cero silencioso.

**B. Esperar a que Movilidad publique un evento de incidentes viales.** ❌
No está registrado ni anunciado, y la entrega tiene fecha. Además duplicaría una
fuente que ya tenemos: los incidentes nacen en Emergencias, y Movilidad los
consume igual que nosotros.

**C. Guardar los incidentes que cortan circulación y relacionar los reclamos que
se dan de alta cerca mientras estén abiertos.** ✅
Es el mismo patrón que el ADR 0013 ya usa con las actividades masivas: una tabla
propia que copia el registro ajeno, poblada desde el handler, consultada dentro
de la transacción del alta del reclamo.

## Decisión

Se adopta **C**.

### Qué se guarda, y qué no

Solo los incidentes que **cortan circulación** (`afectaCirculacion = true`) y que
**traen coordenadas**. Una emergencia médica le concierne a una persona, no a la
calle; y un incidente sin posición no puede ser la causa de nada, porque sin
posición no hay "cerca".

Un incidente que no se guarda **igual escala** los reclamos abiertos de la zona,
como hasta ahora: eso no cambió.

La columna `incidente_origen_id` es `UNIQUE`: el gateway entrega *at-least-once* y
un reenvío no puede duplicar el incidente.

### Cuándo un reclamo queda causado por un incidente

Al darlo de alta, si tiene coordenadas y cae a **300 m o menos** de un incidente
abierto. Con dos en rango, gana el más cercano.

**El radio es deliberadamente más chico que el de la escalada**, que es de 1 km
(`incidente_radio_metros`): subirle la prioridad a un reclamo cercano es barato y
reversible, mientras que **declarar una causa es una afirmación que Analítica
cuenta**. No son la misma decisión y no merecen el mismo umbral.

### Cuándo deja de estar abierto

Cuando llega `EmergenciaActualizada` con un `estadoNuevo` que reconocemos como
final. La lista de valores aceptados es corta y explícita, en los dos géneros y
en los dos idiomas.

**Un estado que no reconocemos deja el incidente abierto, a propósito.** Cerrarlo
ante una palabra de la que no estamos seguros dejaría de relacionar reclamos que
sí están causados por una calle que sigue cortada, y en silencio.

### La red de seguridad

`incidente_vigencia_horas` (24 por defecto) cierra solo un incidente cuyo evento
de cierre nunca llegó. **No es el mecanismo principal** —para eso está
`EmergenciaActualizada`—, sino lo que impide que un evento perdido deje una calle
"cortada" para siempre.

### La precedencia

Un reclamo puede caer bajo una alerta climática, cerca de un incidente y cerca de
una actividad al mismo tiempo. El orden, de más explicativo a menos:

```
EVENTO_CLIMATICO  >  INCIDENTE_VIAL  >  EVENTO_PUBLICO
```

La alerta gana porque explica **por qué** existe el reclamo sobre toda la zona; el
incidente también explica el porqué, pero de una calle cortada dentro de esa zona;
la actividad explica solo **dónde**.

Como en el ADR 0016, la elección es segura porque **`alertaId` y `actividadId`
viajan aparte de la causa**: Analítica puede contar el reclamo de los dos lados
aunque `causaTipo` diga una sola cosa.

## Consecuencias

**Positivas**

- La métrica 4 de Analítica pasa a tener fuente, sin depender de un evento que no
  existe ni de un tercero.
- El incidente queda consultable: antes su id vivía dentro de un texto libre.
- La relación se guarda en la misma transacción que el alta del reclamo, así que
  o están los dos o no está ninguno.

**Negativas**

- **Duplicamos un registro ajeno.** La tabla `incidentes_viales` es una copia
  parcial de lo que vive en Emergencias, y puede quedar desactualizada si ellos
  cambian algo que no publican.
- **Solo refleja el momento del alta**, como toda causa del ADR 0016: un reclamo
  abierto antes del incidente no se relaciona con él aunque esté al lado.
- **El `incidente_id` no tiene clave foránea hacia Emergencias**, obviamente, así
  que un incidente que ellos borren queda huérfano de nuestro lado.
- Una segunda relación `lazy="joined"` en `Reclamo` suma otro JOIN a cada lectura
  de reclamos. Medido como aceptable; si pesa, el camino es cargar la causa solo
  al publicar.

**Qué queda por revisar**

1. **Avisarle a Analítica que la fuente es `EmergenciaCreada` y no el evento de
   Movilidad que nombra su contrato**, y que el sentido es "reclamo causado por un
   incidente". El sentido inverso —reclamos que *originan* un incidente, que es lo
   que hace Movilidad en el CU-INT-01— ya lo tienen con `afectaCirculacion` y es
   otra métrica.
2. **Suscribirse a `com.citypass.emergencias.EmergenciaActualizada`** en el
   catálogo. Sin eso el handler existe y nunca se ejecuta.
3. Si Emergencias llegara a publicar estados finales con palabras que no están en
   la lista, los incidentes se cerrarían recién por vigencia. Vale preguntarles
   qué valores usan.
