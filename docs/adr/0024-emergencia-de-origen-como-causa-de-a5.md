# ADR 0024 — La emergencia de origen es la causa publicada para los reclamos A5

- **Estado:** Aceptada
- **Fecha:** 2026-11-16
- **Contexto:** Flujo A5 entre Emergencias (G6), Reclamos (G5) y Analítica (G8).
- **Relación con otros ADR:** complementa [0016](0016-causa-del-reclamo-para-analitica.md)
  y [0017](0017-incidentes-viales-como-causa.md) con una regla exclusiva para A5.

## Contexto

Cuando `EmergenciaActualizada` indica `estadoNuevo = RESUELTA` y
`causasRelacionadas` contiene `VIA`, A5 crea un reclamo automático. El evento
trae `emergenciaId`; Reclamos lo conserva en `evento_origen_id` con el prefijo
`emergencia:` para deduplicar entregas de la misma emergencia aunque cambie el
`eventId`. El `correlationId` se conserva por separado.

Antes de esta decisión, `ReclamoCreado` calculaba su única causa solo a partir de
las relaciones geográficas del reclamo. Por eso un A5 sin otras relaciones salía
con `causaId` y `causaTipo` nulos, y uno bajo una alerta o cerca de una actividad
podía publicar esa relación como causa. Analítica necesita identificar la
emergencia que efectivamente originó cada reclamo A5.

## Opciones consideradas

**A. Mantener la causa nula o derivarla solo por proximidad.** ❌
Pierde la emergencia de origen si no quedó un incidente vial abierto cerca. El
handler cierra primero el incidente de esa emergencia, de modo que la proximidad
no identifica de forma fiable el origen del reclamo.

**B. Usar `correlationId` como identificador de la causa.** ❌
Analítica ya usa ese campo con su significado actual y pidió conservarlo.
Además, una correlación no sustituye al `emergenciaId` de G6.

**C. Publicar el `emergenciaId` original como causa de A5.** ✅
La clave de deduplicación ya contiene ese ID sin transformarlo, después de un
prefijo conocido. Se recupera al construir `ReclamoCreado`, sin agregar una
columna ni cambiar el flujo de creación.

## Decisión

Si `evento_origen_id` comienza con el prefijo reservado `emergencia:` y tiene un
ID después de él, `ReclamoCreado` publica ese ID original como `causaId` y
`EMERGENCIA` como `causaTipo`. Esta regla se evalúa antes que las causas por
proximidad. Se aplica únicamente a los reclamos A5; en los demás reclamos sigue
vigente el orden `EVENTO_CLIMATICO > INCIDENTE_VIAL > EVENTO_PUBLICO` de los ADR
0016 y 0017.

`alertaId` y `actividadId` continúan viajando como campos independientes cuando
hay esas relaciones. Las asociaciones y prioridades del reclamo no cambian. El
`correlationId` conserva su origen y valor anteriores, incluido `null` cuando
no fue informado: no se reemplaza por `emergenciaId`.

El esquema local y el registrado en EDA declaran `causaId` y `causaTipo` como
`["null", "string"]`. Por eso el valor `EMERGENCIA` no altera la estructura Avro
ni requiere registrar otra versión. Se actualiza solo la descripción local del
campo.

## Consecuencias

**Positivas**

- Analítica puede unir el reclamo A5 con la emergencia de G6 mediante el
  `emergenciaId` original, sin interpretar el prefijo interno.
- La deduplicación, la clasificación con IA, la persistencia y la publicación
  mediante el gateway mantienen su funcionamiento.
- Los reclamos ajenos a A5 conservan la precedencia anterior.

**Negativas**

- `causaId` / `causaTipo` admiten una sola causa. Si A5 coincide con una alerta,
  la alerta sigue en `alertaId`; si coincide con una actividad, esta sigue en
  `actividadId`. Un incidente vial distinto que también esté relacionado no
  tiene un campo independiente en `ReclamoCreado`.
- Los eventos A5 ya publicados no se corrigen automáticamente. Una reentrega
  de la emergencia se deduplica y no vuelve a publicar `ReclamoCreado`.
