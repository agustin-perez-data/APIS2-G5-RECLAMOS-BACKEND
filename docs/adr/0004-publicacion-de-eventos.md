# ADR 0004 — Publicación de eventos: post-commit, con outbox como deuda

- **Estado:** Aceptada (con deuda técnica registrada)
- **Fecha:** 2026-08-13
- **Contexto:** Sprint 0 · Grupo 5

## Contexto

Un caso de uso hace dos cosas que tienen que quedar consistentes: escribe en
PostgreSQL y publica un evento en Kafka. Son dos sistemas distintos, así que no
hay transacción que los abarque. Hay que elegir qué falla y cómo.

## Opciones consideradas

### A. Publicar antes del commit

- ❌ Descartada de entrada. Si el commit falla después, anunciamos al resto de
  la ciudad un reclamo que no existe. Un consumidor podría notificar al vecino
  por un reclamo fantasma. Inconsistencia visible para el usuario final.

### B. Publicar dentro de la transacción, sincrónicamente

- ❌ La transacción de base queda abierta esperando la red al broker. Si Kafka
  está lento, se agotan las conexiones de Postgres. El fallo de un sistema
  secundario tira abajo el principal.

### C. Publicar después del commit *(elegida para esta etapa)*

Primero `commit()`, después `publish()`.

- ✅ La base es la fuente de verdad y nunca queda bloqueada por el broker.
- ✅ Simple: se lee y se entiende sin infraestructura adicional.
- ❌ Ventana de pérdida: si el proceso muere entre el commit y el envío, ese
  evento no se publica nunca. El reclamo existe pero nadie se enteró.

### D. Outbox transaccional

El evento se escribe en una tabla `outbox` **dentro de la misma transacción**, y
un proceso aparte la lee y publica.

- ✅ Cero pérdida: si el commit pasó, el evento está garantizado.
- ✅ Es la solución correcta y la que usaríamos en producción.
- ❌ Requiere tabla, índices, proceso relay, política de reintentos, limpieza de
  procesados y monitoreo del lag. Es una feature en sí misma.

## Decisión

Adoptamos **C** para los sprints iniciales, con **D** registrada como deuda
técnica explícita.

Fundamento: la ventana de pérdida es de milisegundos y requiere que el proceso
muera exactamente ahí. En un TP académico, con volumen bajo y sin dinero de por
medio, el costo esperado de esa pérdida es menor que el costo de construir y
mantener el relay durante el sprint 1. Preferimos gastar ese esfuerzo en el
consumo confiable (idempotencia + DLQ), que es donde los fallos **sí** son
frecuentes: reentregas de Kafka, rebalanceos, mensajes malformados de otros
equipos.

Lo que **sí** implementamos ahora:

1. Productor con `acks="all"` e idempotencia habilitada: sin pérdida ni
   duplicados por reintentos del productor.
2. Consumidor con commit **manual** del offset, después de procesar
   (*at-least-once*).
3. Idempotencia en el consumo vía `evento_origen_id` UNIQUE.
4. DLQ (`reclamos.dlq`) para mensajes que fallan, con commit del offset igual:
   un mensaje envenenado no bloquea la partición.

## Criterio de disparo para implementar el outbox

Cualquiera de estos: (a) un consumidor toma decisiones con impacto real sobre el
vecino a partir de nuestros eventos, (b) detectamos una pérdida en las demos, o
(c) llegamos al Sprint 6 con margen. Ubicación prevista: tabla `outbox` +
relay dentro de `app/worker.py`.

## Consecuencias

**Positivas.** El código del servicio se lee de corrido, sin indirección. La
base nunca depende de la disponibilidad de Kafka.

**Negativas.** No podemos afirmar "cero pérdida de eventos". Está documentado en
el docstring de `ReclamoService` para que nadie lo asuma por error.
