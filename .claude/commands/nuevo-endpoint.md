---
description: Agrega un endpoint REST siguiendo las capas y convenciones del repo
argument-hint: <descripcion del endpoint>
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Agregá el endpoint pedido respetando las reglas de capas de `CLAUDE.md`.

**Endpoint a implementar:** $ARGUMENTS

## Orden obligatorio

1. **Schemas** (`app/schemas/reclamo.py`): DTO de entrada y de salida con
   validación Pydantic (longitudes, rangos, enums del dominio). Los
   `description` de los campos van en español: salen en el OpenAPI que leen los
   otros grupos.

2. **Caso de uso** (`app/services/reclamo_service.py`): toda la regla de negocio
   va acá. El servicio **no importa FastAPI**. Si necesita datos nuevos, agregá
   el método al repositorio primero.

3. **Repositorio** (`app/repositories/reclamo_repository.py`) si hace falta:
   solo queries. Hace `flush()`, **nunca `commit()`**.

4. **Router** (`app/api/v1/reclamos.py`): thin. Traduce DTO ↔ servicio y nada
   más. Con `summary` y `description` en español.

5. **Test de integración** (`tests/integration/test_reclamos_api.py`) y, si la
   regla de negocio es no trivial, también en
   `tests/integration/test_reclamo_service.py`.

## Reglas que no se negocian

- **Identidad**: `UsuarioDep` (cualquier autenticado) o `StaffDep`
  (operador/admin). Ningún endpoint nuevo sin una de las dos.
- **Errores**: lanzá excepciones de dominio de `app/core/exceptions.py`, nunca
  `HTTPException` desde el servicio. Si el error no existe, creá la subclase de
  `DomainError` con `status_code`, `title` (español) y `code`.
- **Rutas fijas antes que las paramétricas**: `/reclamos/estadisticas` tiene que
  declararse antes que `/reclamos/{reclamo_id}` o la captura el path param.
- **Comentarios en inglés**, identificadores del dominio en español.
- Si el endpoint cambia el estado de un reclamo, tiene que **publicar el evento
  correspondiente** y dejar registro en el historial.

## Al terminar

Corré `ruff check . --fix`, `ruff format .` y `pytest`. Mostrame el diff de la
firma del endpoint nuevo y qué tests agregaste.
