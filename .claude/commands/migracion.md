---
description: Genera y revisa una migración de Alembic
argument-hint: <descripcion corta del cambio de esquema>
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Generá la migración para el cambio de esquema pedido.

**Cambio:** $ARGUMENTS

## Pasos

1. Modificá primero el modelo ORM en `app/db/models/`.
2. Generá la revisión:
   ```
   alembic revision --autogenerate -m "descripcion corta"
   ```
   Si no hay base disponible, escribí el archivo a mano en
   `alembic/versions/` siguiendo el estilo de `0001_esquema_inicial.py`.
3. **Leé el archivo generado entero antes de darlo por bueno.** El autogenerate
   se equivoca seguido: inventa drops de índices que no cambiaron, no detecta
   renames (los ve como drop + add, que pierde datos) y a veces se olvida los
   `server_default`.
4. Verificá que el `downgrade()` esté completo y sea el inverso exacto. Es lo
   que corre el CI.
5. Aplicá y revertí contra Postgres local:
   ```
   docker compose up -d postgres
   alembic upgrade head
   alembic downgrade -1
   alembic upgrade head
   ```
   Si Docker no está corriendo, al menos validá el SQL con
   `alembic upgrade head --sql`.
6. Corré `pytest`: los tests crean el esquema desde los modelos, así que si la
   migración y los modelos divergen no lo vas a detectar ahí — por eso el paso 5
   no es opcional.

## Convenciones del repo

- **Una migración por PR** como máximo.
- Los enums del dominio se guardan como `VARCHAR(32)`, no como tipo nativo de
  Postgres: agregar una categoría **no requiere migración**. Si estás por crear
  un `sa.Enum` nativo, parate y releé `app/db/types.py`.
- Nada de tipos específicos de un motor: los tests corren en SQLite.
- Contra Supabase, migrá con el **session pooler (puerto 5432)**, no con el
  transaction pooler.
- Si la columna nueva es `NOT NULL` sobre una tabla con datos, la migración
  necesita tres pasos: agregar nullable → backfill → alterar a not null.
  Decímelo si es el caso.

Al terminar, mostrame el `upgrade()` y el `downgrade()` y confirmá que probaste
el ciclo completo.
