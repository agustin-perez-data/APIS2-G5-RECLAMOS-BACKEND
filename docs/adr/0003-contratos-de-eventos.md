# ADR 0003 — Contratos de eventos: envelope propio compatible con CloudEvents

- **Estado:** Aceptada
- **Fecha:** 2026-08-13
- **Contexto:** Sprint 0 · Grupo 5

## Contexto

Ocho equipos publican y consumen en el mismo bus, cada uno avanzando a su ritmo.
Necesitamos un formato de mensaje que: (a) permita trazar una operación que
cruza módulos, (b) no se rompa cuando otro equipo agrega un campo, y (c) se
pueda versionar sin coordinar un despliegue simultáneo de los ocho.

El Grupo 1 define la convención general del bus; nosotros definimos la forma
concreta de nuestros payloads.

## Opciones consideradas

### A. JSON libre, sin envelope

Cada evento manda directamente sus campos.

- ✅ Cero ceremonia.
- ❌ No hay dónde poner id de evento, timestamp ni correlación sin ensuciar el
  payload de negocio.
- ❌ Sin `event_id` no hay idempotencia posible en el consumidor.

### B. CloudEvents estricto (spec CNCF)

- ✅ Estándar de industria, tooling existente.
- ❌ Nombres muy cortos (`id`, `type`, `time`, `source`) que en el código quedan
  ambiguos y chocan con variables locales.
- ❌ Atarnos a la spec completa (`datacontenttype`, `subject`, `dataschema`,
  modos binary/structured) es más ceremonia de la que este TP necesita.

### C. Envelope explícito con alias de CloudEvents *(elegida)*

Campos con nombres largos y claros, más `AliasChoices` que aceptan también la
forma corta de CloudEvents al **consumir**.

- ✅ Legible en el código y en la consola de Redpanda.
- ✅ Interoperable: si el Grupo 1 termina imponiendo CloudEvents puro, nuestros
  consumers ya lo parsean sin cambios.
- ⚠️ No somos CloudEvents "certificados"; es un superset pragmático.

## Decisión

Adoptamos la opción **C**. Envelope (`app/events/contracts.py`):

```json
{
  "event_id": "uuid",
  "event_type": "reclamos.reclamo.creado",
  "event_version": "1.0",
  "occurred_at": "ISO-8601 UTC",
  "source": "reclamos",
  "correlation_id": "id de la operacion end-to-end",
  "data": { }
}
```

Reglas que se derivan:

1. **Naming:** `<modulo>.<agregado>.<hecho>`, minúsculas, hecho en pasado.
2. **Key del mensaje:** siempre el id del agregado. Garantiza orden por reclamo
   dentro de una partición.
3. **Versionado:** agregar un campo opcional mantiene `event_version`; quitar,
   renombrar o cambiar el tipo de un campo obliga a subir la versión mayor y
   publicar en paralelo hasta que los consumidores migren.
4. **Tolerancia al consumir:** los payloads entrantes se declaran con
   `extra="allow"` y solo listan los campos de los que dependemos. Que otro
   equipo agregue campos nunca puede tirar abajo nuestro worker.
5. **Idempotencia:** el consumidor guarda `event_id` en `evento_origen_id` con
   restricción UNIQUE. Un redelivery de Kafka no duplica reclamos.
6. **Correlación:** el `X-Correlation-Id` del request HTTP se propaga al evento
   y a todos los logs estructurados.

## Consecuencias

**Positivas.** Los tests de contrato (`tests/unit/test_contracts.py`) verifican
que aceptamos tanto nuestro formato como CloudEvents puro y que los campos
extra no rompen nada. La idempotencia está probada con un test que procesa el
mismo evento dos veces.

**Negativas.** Al no ser CloudEvents estricto, no podemos usar tooling que lo
asuma. Si el Grupo 1 lo exige, la migración es cambiar los alias de
serialización — el trabajo real (idempotencia, correlación, versionado) ya está.
