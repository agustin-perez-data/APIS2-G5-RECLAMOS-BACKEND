# ADR 0016 — Causa del reclamo en `ReclamoCreado` para Analítica

- **Estado:** Aceptada
- **Fecha:** 2026-11-05
- **Contexto:** G5D-452 · Caso de uso transversal del squad 3 · Grupo 5
- **Completa:** el punto 2 de "Qué queda por revisar" del
  [ADR 0013](0013-reclamos-relacionados-con-actividades-masivas.md), que preveía
  sumar la actividad a `ReclamoCreado` si Analítica la necesitaba.

## Contexto

Analítica arma para la Parte 2 un tablero de 30 métricas, y su
`CONTRATO_RECLAMOS.md` (29/10) nos pide un solo cambio: sumar a `ReclamoCreado` el
par `causaId` / `causaTipo`, que dice qué originó el reclamo. Analítica no infiere
causas: cuenta lo que viene en el evento.

Los cinco módulos comparten el vocabulario de `causaTipo`. De los valores que nos
piden, dos los resuelve Reclamos con reglas que ya existen:

- `EVENTO_PUBLICO`: el reclamo quedó relacionado con una actividad masiva
  (ADR 0013). Es la métrica 3, "reclamos relacionados al evento masivo".
- `EVENTO_CLIMATICO`: el reclamo cayó en el área de una alerta climática
  (ADR 0014). Es la métrica 1.

El documento de Analítica dice que `EVENTO_PUBLICO` sale de `EventoPublicoCreado`,
pero ese evento no existe en el bus. El 3/11 Analítica le confirmó a Espacios que
es equivalente a `com.citypass.espacios.ActividadCreada`, que es justamente el que
consumimos.

Hay un problema de forma: **un reclamo tiene una sola causa.** Uno que cae en una
alerta climática y a la vez cerca de un festival tiene las dos cosas, y nuestro
modelo las guarda por separado (`alerta_id` y `actividad_id`), pero el contrato
pedido solo deja pasar una.

`ReclamoCreado` todavía no está registrado en el catálogo del Grupo 1 con nuestro
schema, así que lo que se agregue ahora entra en el primer registro.

## Opciones consideradas

### A. Solo `causaId` / `causaTipo`, tal cual lo pidió Analítica

- ✅ Es exactamente el contrato que pidieron.
- ❌ El reclamo que tiene las dos causas se cuenta en la métrica 1 y **desaparece
  de la métrica 3**, sin que nadie lo note hasta que los números no cierren.

### B. Una lista de causas

- ✅ No pierde nada.
- ❌ Cambia la forma del contrato de Analítica, que ya está escrito para los cinco
  módulos con un par de campos simples.
- ❌ Un array de records en Avro es bastante más difícil de consumir y de validar
  que dos strings.

### C. La causa única más `actividadId` como campo aparte *(elegida)*

- ✅ Respeta el contrato de Analítica tal cual.
- ✅ La métrica 3 se puede contar con `actividadId` no nulo y ya no depende de
  qué causa ganó.
- ✅ Analítica ya aceptó sumar campos ("si necesitan agregar campos no hay
  problema"), y como el schema todavía no está registrado no hay que coordinar un
  segundo registro.
- ❌ El mismo dato viaja dos veces cuando la causa es la actividad.

## Decisión

Adoptamos **C**. `ReclamoCreado` suma tres campos, todos al final del schema y con
`null` por defecto, para que sea compatible con cualquier versión anterior:

| Campo | Valor |
| --- | --- |
| `causaId` | Id de la entidad que originó el reclamo, tal como la publica su módulo. |
| `causaTipo` | `EVENTO_CLIMATICO`, `INCIDENTE_VIAL`, `EVENTO_PUBLICO` o `RESERVA`. `null` si y solo si `causaId` es `null`. |
| `actividadId` | El `actividadId` de Espacios de la actividad masiva relacionada, o `null`. |

**`causaId` y `actividadId` llevan el id de Espacios** (el `actividadId` de
`ActividadCreada`), no el UUID interno de la tabla `actividades_masivas`: es el
que Analítica puede cruzar con el evento de Espacios.

**Si hay dos causas, gana la alerta climática.** La alerta explica por qué existe
el reclamo; la actividad solo dice dónde. Una tormenta es la razón de que se caiga
un árbol, mientras que un festival a 200 m es una coincidencia de ubicación. Lo
acordamos con el caso del modo evento climático.

**Se completan en dos pasos.** Este ADR entra con `EVENTO_PUBLICO`. La rama
`EVENTO_CLIMATICO`, con su prioridad sobre la actividad, la suma el caso climático
encima, en un PR aparte. Hasta entonces un reclamo con las dos causas sale como
`EVENTO_PUBLICO`.

## Consecuencias

**Positivas.** Analítica puede sacar las métricas 1 y 3 sin inferir nada, y la 3 no
pierde reclamos por la prioridad de la climática. El test de schemas Avro obliga a
que el `.avsc` y lo que mandamos sigan diciendo lo mismo.

**Negativas.**
- Analítica tiene que contar la métrica 3 por `actividadId` y no por
  `causaTipo = EVENTO_PUBLICO`, como decía su documento. Hay que avisarles.
- Como en el ADR 0013, un reclamo cargado antes de que llegue la actividad no
  tiene causa: la relación nace en el alta y no se recalcula.

**Qué queda por revisar.**
1. Sumar la rama `EVENTO_CLIMATICO` (caso climático).
2. `INCIDENTE_VIAL` y `RESERVA` quedan declarados en el enum pero ningún caso de
   Reclamos los completa todavía.
