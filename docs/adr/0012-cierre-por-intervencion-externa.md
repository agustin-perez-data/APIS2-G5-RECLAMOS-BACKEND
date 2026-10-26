# ADR 0012 — Cierre de un reclamo por intervención de otro módulo

- **Estado:** Aceptada
- **Fecha:** 2026-10-26
- **Contexto:** Caso de uso integrado CU-INT-01 · Grupo 5

## Contexto

CU-INT-01 termina fuera de Reclamos. El vecino reporta un auto sobre la ciclovía,
nosotros registramos y derivamos, y es **Espacios Públicos y Cultura** quien
resuelve en la calle. Cuando terminan nos avisan con
`com.citypass.espacios.IntervencionFinalizada`, y recién ahí el reclamo se puede
cerrar.

Ese evento choca con nuestra máquina de estados. `TRANSICIONES_VALIDAS` exige
`RECIBIDO → ASIGNADO → EN_PROCESO → RESUELTO`, y el reclamo que nos devuelven
suele estar todavía en `RECIBIDO`: nadie de nuestro lado lo asignó ni lo trabajó,
porque el trabajo lo hizo otro módulo. Aplicado tal cual, el evento se rechaza
con `TransicionInvalida` y el reclamo del vecino queda abierto para siempre.

Hay un segundo problema, de producto. Espacios nos avisa aunque **no** hayan
intervenido: si no hacía falta una grúa, mandan el mismo evento igual. "No hacía
falta grúa" no es lo mismo que "se resolvió" — puede ser que el auto ya se haya
ido, pero también que no estuviera bloqueando o que no fuera jurisdicción de
ellos. Si todo eso cae en `RESUELTO`, le decimos al vecino que su reclamo se
solucionó mientras el auto sigue ahí.

## Opciones consideradas

### A. Recorrer la máquina paso a paso

Al recibir el evento, hacer `RECIBIDO → ASIGNADO → EN_PROCESO → RESUELTO`
encadenando transiciones válidas.

- ✅ No toca la máquina de estados.
- ❌ **Inventa una historia que no ocurrió.** `ASIGNADO` significa que un
  operador nuestro se hizo cargo y `EN_PROCESO` que lo estaba trabajando.
  Ninguna de las dos pasó: el trabajo fue de otro módulo. El historial del
  reclamo pasaría a mentir, y es justamente la pantalla que mira el vecino.
- ❌ Dispara tres notificaciones al vecino en el mismo segundo, y tres
  `ReclamoActualizado` al gateway por una sola acción real.

### B. Relajar la máquina para permitir el salto

Agregar `RESUELTO` a las transiciones válidas desde `RECIBIDO`.

- ❌ Abre el salto para **todos**, incluido un operador nuestro por la API. La
  regla existe para que un reclamo no figure resuelto sin haber sido trabajado;
  relajarla para un caso la desactiva para todos.

### C. Un camino propio para el cierre externo *(elegida)*

Un método de servicio que lleva el reclamo a su estado final en un solo paso,
sin pasar por la validación de la máquina, y deja asentado en el historial que el
cambio vino de afuera.

- ✅ El historial dice la verdad: el reclamo pasó de `RECIBIDO` a `RESUELTO`
  porque otro módulo intervino, y eso es exactamente lo que ocurrió.
- ✅ Una notificación y un evento por acción real.
- ✅ La máquina sigue intacta para todo lo que entra por la API.
- ❌ Hay un segundo camino para cambiar de estado, que hay que mantener.

## Decisión

Adoptamos **C**, en `ReclamoService.finalizar_por_intervencion`.

Para no duplicar nada, lo que antes era el cuerpo de `cambiar_estado` se extrajo
a `_aplicar_cambio_estado`: escribe el cambio, el historial, la notificación y
los eventos. `cambiar_estado` valida la transición y delega; el cierre por
intervención delega directo. **La validación es lo único que se saltea**, no el
resto del comportamiento.

### `resultado` decide el estado final

| `resultado` | Estado | Qué lee el vecino |
| --- | --- | --- |
| `RESUELTO` | `RESUELTO` | "El area responsable intervino en la via publica y dio por resuelto el reclamo." |
| `RECHAZADO` | `RECHAZADO` | "El area responsable reviso el reclamo y no correspondia una intervencion." |

El texto lo **generamos nosotros**, no viene en el evento. Espacios nos informa
el desenlace, no qué hicieron, así que una redacción más específica correría el
riesgo de afirmar algo que no pasó. Es deliberadamente genérico; si más adelante
nos mandan el detalle, se reemplaza por el suyo.

### Idempotencia

El gateway entrega *at-least-once*. No hay tabla de eventos procesados: si el
reclamo ya está en el estado destino, o ya está en un estado final, el método no
hace nada y devuelve `None`. Una reentrega encuentra el trabajo hecho y se va,
que es la misma forma de idempotencia que usan los otros handlers.

Un evento sobre un reclamo que no existe también devuelve `None` y se loguea:
un 500 haría que el gateway reintente para siempre por algo que nunca va a
funcionar.

## Consecuencias

**Positivas.** El caso de uso cierra de punta a punta y el vecino se entera del
desenlace real. El historial no inventa pasos.

**Negativas.** Hay dos caminos para cambiar de estado. El riesgo es que alguien
agregue una regla en `cambiar_estado` y se olvide de que este camino existe; por
eso la lógica común vive en `_aplicar_cambio_estado` y lo único que diverge es
la validación.

**Qué queda por revisar.** `RECHAZADO` es terminal y, hasta este cambio, ningún
camino del código lo producía. Si el vecino tiene que poder discutir un rechazo,
hace falta una transición de salida que hoy no existe (US-08, reabrir un
reclamo).
