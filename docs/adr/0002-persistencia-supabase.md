# ADR 0002 — Persistencia: Supabase con SQLAlchemy async + Alembic

- **Estado:** Aceptada
- **Fecha:** 2026-08-13
- **Contexto:** Sprint 0 · Grupo 5

## Contexto

La cátedra pide despliegue en la nube y el equipo eligió **Supabase** como base
gestionada (PostgreSQL + panel + tier gratuito, sin tarjeta de crédito). Falta
decidir *cómo* le hablamos desde FastAPI.

Requisitos: el esquema tiene que estar versionado en git (lo pide la rúbrica de
DevOps), los tests tienen que correr en cualquier notebook y en CI sin depender
de Supabase, y la API es async de punta a punta.

## Opciones consideradas

### A. `supabase-py` (cliente oficial, sobre PostgREST)

- ✅ Arranca en cinco minutos, sin configurar conexiones.
- ✅ Row Level Security y Storage integrados.
- ❌ El esquema se edita **por el panel web**: no queda en git, no hay
  migraciones versionadas, no hay revisión en PR. Pierde puntos de DevOps.
- ❌ Cliente sincrónico: bloquea el event loop de FastAPI.
- ❌ Los tests necesitarían un proyecto Supabase real o un mock del HTTP.
- ❌ Acopla el código a un producto, no a PostgreSQL.

### B. asyncpg "pelado", SQL a mano

- ✅ Control total y máximo rendimiento.
- ❌ Todo el mapeo fila→objeto lo escribimos nosotros.
- ❌ Sin migraciones ni relaciones: mucha superficie para bugs tontos en un
  equipo que está aprendiendo.

### C. SQLAlchemy 2.0 async + Alembic *(elegida)*

Conexión Postgres directa con `asyncpg`, ORM tipado y migraciones versionadas.

- ✅ Las migraciones son archivos en git, revisables en PR y aplicables en CI.
- ✅ Async nativo, coherente con FastAPI.
- ✅ Los tests corren contra SQLite en memoria: cero dependencia de red.
- ✅ Portable: si mañana movemos la base a otro Postgres, cambia una variable.
- ⚠️ Hay que resolver a mano las particularidades del pooler de Supabase.

## Decisión

Adoptamos la opción **C**.

Detalles de implementación (`app/db/session.py`, `app/core/config.py`):

1. La URI que da el panel de Supabase se pega tal cual: un validator reescribe
   `postgresql://` a `postgresql+asyncpg://`.
2. `sslmode` de libpq no lo entiende asyncpg: se traduce a un contexto SSL.
3. El **transaction pooler** (puerto 6543, pgbouncer) no soporta prepared
   statements. Al detectar ese puerto se desactivan los caches y se usa
   `NullPool` — pgbouncer ya hace el pooling.
4. **Migraciones contra el session pooler** (puerto 5432); la API puede usar el
   transaction pooler.
5. Los enums del dominio se persisten como `VARCHAR(32)`, no como tipo nativo de
   Postgres: agregar una categoría no requiere migración y el mismo modelo corre
   en SQLite.

## Consecuencias

**Positivas.** El esquema es código revisable. La suite corre offline en ~3
segundos. El CI aplica y revierte las migraciones contra un PostgreSQL real en
cada push, así que un `downgrade` roto se detecta antes del merge.

**Negativas.** Perdemos las funciones "batería incluida" de Supabase: si más
adelante queremos Row Level Security o Storage para las fotos, hay que
integrarlas aparte.

**Riesgo asumido.** SQLite en tests y PostgreSQL en producción no son idénticos.
Lo mitigamos evitando tipos y funciones específicas de un motor, y corriendo las
migraciones contra Postgres real en CI.
