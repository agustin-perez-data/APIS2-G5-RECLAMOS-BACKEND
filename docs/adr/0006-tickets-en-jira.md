# ADR 0006 — Un ticket en Jira por cada reclamo, con llamada post-commit

- **Estado:** Aceptada (con deuda técnica registrada)
- **Fecha:** 2026-09-23
- **Contexto:** Grupo 5

## Contexto

El equipo armó en Jira el proyecto **REC** para gestionar los reclamos desde un
tablero (Recibido → En gestión → Resuelto). Cada reclamo nuevo, además de
guardarse en la base, tiene que abrir un ticket ahí.

Restricciones reales: el deploy de Railway corre **sin Kafka**
(`KAFKA_ENABLED=false`), y un problema de Jira no puede impedir que un vecino
cargue su reclamo.

## Opciones consideradas

### A. El worker consume `reclamos.reclamo.creado` y abre el ticket

- ✅ Es la forma correcta en esta arquitectura: cero latencia en el alta,
  reintentos gratis por el reprocesamiento de Kafka, y Jira queda como un
  consumidor más del bus.
- ❌ Hoy no funcionaría: en el deploy no hay broker, así que ningún ticket se
  abriría.

### B. `BackgroundTasks` de FastAPI desde el router

- ✅ No suma latencia a la respuesta.
- ❌ El servicio no puede usarlo sin importar FastAPI, lo que rompe la regla de
  capas del ADR 0001. Y los reclamos que nacen de eventos no pasan por el router,
  así que se quedarían sin ticket.

### C. Llamada desde el servicio, después del commit *(elegida)*

El mismo patrón que la publicación de eventos del ADR 0004: primero se confirma
el reclamo y después se llama a Jira.

- ✅ Funciona hoy, sin broker, y cubre las dos vías de alta: la app y los eventos.
- ✅ El servicio depende del puerto `SistemaTickets`, no de Jira: los tests
  usan `TicketsEnMemoria` y nunca tocan la red.
- ⚠️ Suma la latencia de Jira al alta, con un tope de `JIRA_TIMEOUT_SEGUNDOS` (5 s).

## Decisión

Adoptamos **C**, con **A** registrada como deuda.

1. La llamada va después del commit. Si Jira falla o no responde, el reclamo
   **se crea igual**: se loguea `reclamo.ticket_fallido` y listo.
2. La clave del ticket se guarda en `reclamos.ticket_externo` (UNIQUE,
   nullable). Un reclamo con la columna vacía es uno cuyo ticket falta: se
   encuentran con una sola consulta, y eso es lo que permite reintentar.
3. El ticket no lleva el `ciudadano_id`. Jira es una herramienta de terceros y
   con el id del reclamo alcanza para llegar a todo lo demás.
4. La prioridad se traduce al esquema estándar de Jira por id (`CRITICA` →
   Highest, `ALTA` → High, `MEDIA` → Medium, `BAJA` → Low): los nombres se
   muestran traducidos y cambian con el idioma de la cuenta.

## Criterio para pasar a la opción A

Cualquiera de estos: (a) el deploy suma un broker, (b) Jira empieza a demorar
el alta de forma visible, o (c) hay que sincronizar los estados en las dos
direcciones (mover la tarjeta en Jira cambia el reclamo). Ahí conviene un
consumidor del bus con reintentos, en lugar de más llamadas desde el servicio.

## Consecuencias

**Positivas.** Cada reclamo aparece en el tablero en la columna **Recibido**, con
su categoría, prioridad y ubicación. Se verificó de punta a punta contra el
proyecto REC real.

**Negativas.** No hay reintento automático: si Jira estaba caído, el ticket se
abre a mano o con un script sobre los reclamos con `ticket_externo` vacío. Y los
cambios de estado todavía no se reflejan en Jira: la tarjeta queda en Recibido
aunque el reclamo avance.
