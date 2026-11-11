# ADR 0018 — Una actividad cancelada o suspendida deja de relacionar reclamos

- **Estado:** Aceptada
- **Fecha:** 2026-11-11
- **Contexto:** G5D-467 · Squad 3 · Grupo 5
- **Completa:** el punto 1 de "Qué queda por revisar" del
  [ADR 0013](0013-reclamos-relacionados-con-actividades-masivas.md), que dejaba
  la cancelación para cuando Espacios la publicara.

## Contexto

El ADR 0013 relaciona con una actividad masiva cada reclamo que se carga cerca
de ella, desde que empieza hasta 6 h después de que termina. Como negativa
anotó que **una actividad cancelada después de creada seguía relacionando
reclamos**, porque Espacios no publicaba cancelaciones.

Ahora sí las publica. En vez de un `ActividadCancelada`, Espacios registró
`com.citypass.espacios.ActividadModificada`, con `estadoAnterior`,
`estadoNuevo`, `motivo`, `causaId`, `causaTipo`, `modificadaEn` y el mismo
`correlationId` que `ActividadCreada` (`act-<actividadId>`). Rodrigo (Espacios)
nos confirmó cómo lo usa:

- hoy lo publica solo al cancelar (`estadoNuevo = CANCELADA`);
- cuando entre su PR de clima, también al suspender (`SUSPENDIDA`);
- cuando una actividad se reanuda, llega con `estadoNuevo = PROGRAMADA`.

## Opciones consideradas

**A. Borrar la actividad al cancelarla.** ❌
Los reclamos ya relacionados perderían la relación (`ON DELETE SET NULL`), y
una suspendida que se reanuda no tendría a qué volver.

**B. Cerrar la ventana: poner `fin` en el momento de la cancelación.** ❌
Es lo que proponía el ADR 0013, pero deja relacionando reclamos durante las 6 h
posteriores, que es justo lo que no tiene que pasar con una cancelada. Además
pisa el horario real y no se puede deshacer al reanudar.

**C. Guardar el estado y no relacionar mientras esté cancelada o suspendida.** ✅
La actividad conserva su horario y suma `estado`. La búsqueda que corre en cada
alta excluye las canceladas y las suspendidas. Si vuelve a `PROGRAMADA`, se
retoma sola.

## Decisión

Opción C.

- **Qué estados cortan la relación:** solo `CANCELADA` y `SUSPENDIDA` (y sus
  variantes en masculino y en inglés). Cualquier otro, incluido `FINALIZADA`,
  sigue relacionando: la limpieza de las horas posteriores al festival es el
  caso entero, y terminar no es cancelar.
- **Los reclamos ya relacionados no cambian.** Se cargaron mientras la actividad
  estaba vigente, así que la relación era cierta en ese momento.
- **Los que se cargan durante una suspensión no se relacionan después.** La
  relación se decide en el alta, como en el ADR 0013. Si la actividad se
  reanuda, se relacionan los nuevos desde ese momento.
- **Cómo se encuentra la actividad:** por `actividadId`; si no viene o no
  coincide, por `correlationId`. Si no la tenemos guardada (era de menos de
  1.000 personas, no traía coordenadas o su creación nunca llegó), se ignora.
- **Orden y reentregas:** se guarda `modificadaEn` del último cambio aplicado.
  Un cambio más viejo, entregado tarde, se ignora, y uno con el mismo estado no
  hace nada. Así una reentrega del bus es inofensiva.
- **`GET /actividades` muestra el `estado`**, para que el operador entienda por
  qué una actividad dejó de sumar reclamos.

## Consecuencias

**Positivas.**
- Un festival cancelado deja de aparecer como causa de los reclamos de la zona,
  y Analítica deja de contarlos como `EVENTO_PUBLICO`.
- La suspensión por clima ya queda resuelta para cuando Espacios la publique,
  sin otro cambio de nuestro lado.
- Es solo agregado: una columna con valor por defecto y un filtro más en la
  búsqueda. Las actividades guardadas quedan como `PROGRAMADA`, que es lo que
  eran.

**Negativas.**
- Si `ActividadModificada` llega antes que `ActividadCreada`, se ignora y la
  actividad queda vigente. El bus entrega al menos una vez, pero no garantiza
  el orden entre tipos distintos. Lo aceptamos porque Espacios publica la
  modificación mucho después de la creación.
- Los reclamos cargados durante una suspensión quedan sin relacionar aunque la
  actividad se reanude.

**Qué queda por revisar.**
1. Suscribir el webhook a `com.citypass.espacios.ActividadModificada` en el
   portal del bus, con la misma URL que `ActividadCreada`.
2. Si Espacios suma otros estados que deberían cortar la relación, agregarlos
   a `ESTADOS_SIN_RELACION` en `app/services/actividad_service.py`.
