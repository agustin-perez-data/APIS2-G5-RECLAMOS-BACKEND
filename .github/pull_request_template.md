<!--
Titulo del PR: `G5D-<nro>: descripcion corta en imperativo y minuscula`.
Base: `develop`. Borrar las secciones que no apliquen.
-->

## G5D-

### Que resuelve

<!-- El problema, no la solucion. Dos o tres lineas alcanzan. -->

### Como lo resuelve

<!-- Solo si no se entiende leyendo el diff: decisiones tomadas, alternativas
     descartadas y por que. Si no hace falta, borrar la seccion. -->

### Como probarlo

```bash
pytest
```

<!-- Si hace falta algo mas (levantar el broker, correr una migracion, generar
     un token con scripts/dev_token.py), ponerlo aca tal cual se copia y pega. -->

---

## Checklist

- [ ] Los commits llevan el prefijo `G5D-<nro>` y el PR apunta a `develop`.
- [ ] `ruff check .` y `ruff format --check .` pasan.
- [ ] `pytest` pasa y la cobertura no baja (minimo de la rubrica: 60%).
- [ ] Si arregla un bug, entra con un test que fallaba antes del fix.
- [ ] Idioma: comentarios y docstrings en ingles; dominio, `summary`/`description`
      de OpenAPI y `title` de los errores en espanol; sin tildes ni enie en
      identificadores ni en comentarios de codigo.
- [ ] Las dependencias siguen apuntando hacia adentro: `api/` no importa
      `repositories/` ni modelos ORM, `services/` no importa FastAPI, `domain/`
      no importa nada del proyecto.
- [ ] El repositorio hace `flush()`, nunca `commit()`.
- [ ] No hay `.env`, `.venv/`, `coverage.xml` ni `__pycache__` en el diff.

<details>
<summary><b>Si toca la API</b></summary>

- [ ] Schema en `app/schemas/`, caso de uso en `app/services/`, router en `app/api/v1/`.
- [ ] El endpoint declara `UsuarioDep` o `StaffDep`. Ninguno sin identidad salvo `/health`.
- [ ] `summary` y `description` en espanol: es lo que los otros grupos leen en `/docs`.
- [ ] Errores nuevos: subclase de `DomainError` con `status_code`, `title` y `code`.
- [ ] Test de integracion en `tests/integration/test_reclamos_api.py`.

</details>

<details>
<summary><b>Si toca eventos</b></summary>

- [ ] Topic en `app/events/topics.py` y payload Pydantic en `app/events/contracts.py`.
- [ ] Se publica **despues** del commit, con `key=str(reclamo.id)`.
- [ ] Los payloads que consumimos llevan `extra="allow"` y `AliasChoices`.
- [ ] Documentado en `docs/eventos.md`: es el contrato que leen los otros grupos.

</details>

<details>
<summary><b>Si toca la base</b></summary>

- [ ] Una sola migracion en el PR, y el archivo generado esta revisado a mano.
- [ ] `alembic upgrade head` y `alembic downgrade -1` funcionan los dos
      (el CI ademas corre `downgrade base` contra un PostgreSQL real).
- [ ] Los enums nuevos van como `VARCHAR(32)`, no como tipo nativo de Postgres.

</details>

---

## Impacto en otros modulos

<!-- Marcar lo que aplique y avisarle al grupo que corresponda antes de mergear. -->

- [ ] Ninguno.
- [ ] Cambia el contrato REST que consume el front.
- [ ] Cambia un payload de evento (Grupos 1 - EDA, 4 - Residuos, 6 - Emergencias).
- [ ] Cambia `GET /reclamos/estadisticas` o un evento que consume Analitica (Grupo 8).
- [ ] Cambia como se validan los JWT del Grupo 2.

## Decisiones

<!-- Si el PR contradice algo de docs/adr/, va con un ADR nuevo que supere al
     anterior (`/adr`). Si agrega una dependencia, justificarla aca. Si no hay
     nada de esto, borrar la seccion. -->
