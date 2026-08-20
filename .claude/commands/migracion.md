---
description: Generates and reviews an Alembic migration
argument-hint: <short description of the schema change>
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Generate the migration for the requested schema change.

**Change:** $ARGUMENTS

## Steps

1. Change the ORM model in `app/db/models/` first.
2. Generate the revision:
   ```
   alembic revision --autogenerate -m "descripcion corta"
   ```
   If no database is reachable, hand-write the file in `alembic/versions/`
   following the style of `0001_esquema_inicial.py`.
3. **Read the generated file end to end before trusting it.** Autogenerate gets
   things wrong often: it invents drops of indexes that did not change, it does
   not detect renames (it sees drop + add, which loses data), and it sometimes
   misses `server_default`.
4. Check that `downgrade()` is complete and the exact inverse. That is what CI
   runs.
5. Apply and revert against local Postgres:
   ```
   docker compose up -d postgres
   alembic upgrade head
   alembic downgrade -1
   alembic upgrade head
   ```
   If Docker is not running, at least validate the SQL with
   `alembic upgrade head --sql`.
6. Run `pytest`: the tests build the schema from the models, so a drift between
   migration and models will **not** show up there — which is why step 5 is not
   optional.

## Repo conventions

- **One migration per PR** at most.
- Domain enums are stored as `VARCHAR(32)`, not as a native Postgres type:
  adding a category **needs no migration**. If you are about to create a native
  `sa.Enum`, stop and re-read `app/db/types.py`.
- No engine-specific types: the tests run on SQLite.
- Against Supabase, migrate through the **session pooler (port 5432)**, not the
  transaction pooler.
- A new `NOT NULL` column on a table with data needs three steps: add nullable →
  backfill → alter to not null. Tell me if that is the case.

When done, show me `upgrade()` and `downgrade()` and confirm you ran the full
cycle.
