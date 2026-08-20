---
description: Adds a REST endpoint following the repo's layering and conventions
argument-hint: <what the endpoint should do>
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Add the requested endpoint, respecting the layering rules in `CLAUDE.md`.

**Endpoint to implement:** $ARGUMENTS

## Mandatory order

1. **Schemas** (`app/schemas/reclamo.py`): input and output DTOs with Pydantic
   validation (lengths, ranges, domain enums). Field `description` values stay in
   **Spanish**: they end up in the OpenAPI page the other teams read.

2. **Use case** (`app/services/reclamo_service.py`): all business logic goes
   here. The service **must not import FastAPI**. If it needs new data, add the
   repository method first.

3. **Repository** (`app/repositories/reclamo_repository.py`) when needed: queries
   only. It calls `flush()`, **never `commit()`**.

4. **Router** (`app/api/v1/reclamos.py`): thin. It translates DTO ↔ service and
   nothing else. `summary` and `description` in **Spanish**.

5. **Integration test** (`tests/integration/test_reclamos_api.py`) and, when the
   business rule is non-trivial, one in
   `tests/integration/test_reclamo_service.py` too.

## Non-negotiable rules

- **Identity**: `UsuarioDep` (any authenticated user) or `StaffDep`
  (operator/admin). No new endpoint without one of the two.
- **Errors**: raise domain exceptions from `app/core/exceptions.py`, never
  `HTTPException` from the service. If the error does not exist yet, create the
  `DomainError` subclass with `status_code`, `title` (Spanish) and `code`.
- **Fixed routes before parameterised ones**: `/reclamos/estadisticas` must be
  declared before `/reclamos/{reclamo_id}` or the path param swallows it.
- **Comments in English**, domain identifiers in Spanish.
- If the endpoint changes a claim's state, it must **publish the matching event**
  and leave a history entry.

## When done

Run `ruff check . --fix`, `ruff format .` and `pytest`. Show me the new
endpoint's signature and which tests you added.
