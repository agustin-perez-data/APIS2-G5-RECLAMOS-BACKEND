# CLAUDE.md — Convenciones del repo

Guía para cualquiera (persona o agente) que toque este código.
**Módulo:** Reclamos y Participación Ciudadana — Grupo 5, CityPass+ (UADE, DA2 2026 2C).

---

## 1. Stack

| Capa | Elección |
| --- | --- |
| API | Python 3.12+ / FastAPI |
| Persistencia | Supabase (PostgreSQL) vía SQLAlchemy 2.0 async (asyncpg) |
| Migraciones | Alembic |
| Eventos | Kafka — Redpanda en local, cliente `aiokafka` |
| Identidad | JWT emitido por el Grupo 2 (Login Federado LDAP + JWT) |
| Tests | pytest + pytest-asyncio, SQLite en memoria |
| Lint / format | ruff (una sola herramienta para ambos) |

No agregar dependencias sin justificarlo en el PR. En particular, **no** meter
numpy/scipy/sklearn: el clasificador es Python puro a propósito (ver ADR 0005).

---

## 2. Idioma

Esta es la regla que más se olvida, así que va primero:

| Qué | Idioma |
| --- | --- |
| Comentarios y docstrings | **Inglés** |
| Slash commands de `.claude/commands/` | **Inglés** |
| Identificadores del dominio (`reclamo`, `adherir`, `EstadoReclamo`) | **Español** |
| Texto que ve el usuario: `summary`/`description` de OpenAPI, `title` de los errores | **Español** |
| Documentación del repo (README, ADRs, este archivo) | **Español** |
| Mensajes de commit y PR | **Español** |

El dominio es municipal argentino: traducir `reclamo` a `claim` en el código
rompe la trazabilidad con el enunciado, la rúbrica y los otros equipos. Los
comentarios en inglés son la convención de la cátedra para el código.

Sin tildes ni `ñ` en identificadores ni en comentarios de código (evita
problemas de encoding entre Windows y Linux). En la documentación `.md` sí.

---

## 3. Estructura y reglas de capas

```
app/
├── api/          HTTP: routers, dependencias, manejo de errores
├── services/     Casos de uso y reglas de negocio
├── repositories/ Queries SQLAlchemy
├── db/           Engine, sesión, modelos ORM
├── domain/       Enums, máquina de estados, invariantes puras
├── events/       Contratos, producer, consumer, handlers
├── ml/           Clasificador (texto, Naive Bayes, corpus)
├── schemas/      DTOs Pydantic de entrada/salida
├── core/         Config, logging, seguridad, excepciones
├── main.py       App FastAPI
└── worker.py     Proceso consumidor de eventos
```

**Las dependencias apuntan hacia adentro.** Concretamente:

- `api/` puede importar `services/`, `schemas/`, `core/`. **No** importa
  `repositories/` ni modelos ORM directamente.
- `services/` puede importar `repositories/`, `domain/`, `events/`, `db.models`.
  **No** importa nada de `api/` ni de FastAPI.
- `repositories/` solo habla SQLAlchemy. No conoce Pydantic ni HTTP.
- `domain/` no importa nada del proyecto: son reglas puras, testeables solas.
- `ml/` no conoce la base ni la API.

El servicio depende del **puerto** `EventPublisher`, no de Kafka. Por eso los
tests corren sin broker.

### Transacciones

El repositorio hace `flush()`, **nunca `commit()`**. El commit lo hace el
servicio, que es quien sabe cuándo terminó la operación de negocio completa.

### Eventos

Se publican **después** del commit, nunca antes. Un evento que anuncia algo que
después falla es peor que un evento perdido. La deuda (outbox transaccional)
está en el ADR 0004.

---

## 4. Convenciones de código

- **Type hints en todo**: parámetros y retornos. `from __future__ import annotations`
  al tope de cada módulo.
- **Async de punta a punta**: nada de I/O bloqueante dentro de un `async def`.
- **Excepciones de dominio**, no `HTTPException`, en `services/` y
  `repositories/`. La traducción a HTTP vive en `app/api/errors.py`.
- **Errores HTTP**: todos con formato RFC 7807 (`application/problem+json`).
  Al agregar un error nuevo: subclase de `DomainError` con `status_code`,
  `title` y `code`.
- **Logging estructurado**: `log.info("evento.punto_clave", campo=valor)`, nunca
  f-strings. El nombre del evento va en `snake.case` jerárquico.
- **Nada de secretos hardcodeados**. Todo por `Settings` (`app/core/config.py`).
- Línea de 100 caracteres. Lo impone ruff, no la discutas con el reviewer.

### Endpoints nuevos

1. Schema de entrada y salida en `app/schemas/`.
2. Caso de uso en `app/services/`.
3. Router en `app/api/v1/`, con `summary` y `description` en español.
4. Dependencia de identidad: `UsuarioDep` (cualquier usuario autenticado) o
   `StaffDep` (operador/admin). **Ningún endpoint sin una de las dos**, salvo
   `/health`.
5. Test de integración en `tests/integration/test_reclamos_api.py`.

### Eventos nuevos

1. Constante del topic en `app/events/topics.py`.
2. Payload Pydantic en `app/events/contracts.py`.
3. Publicación desde el servicio con `key=str(reclamo.id)`.
4. Documentarlo en `docs/eventos.md` — es el contrato que leen los otros grupos.
5. Los payloads que *consumimos* llevan `extra="allow"` y `AliasChoices`: si otro
   equipo agrega o renombra un campo, nuestro consumer no se cae.

### Migraciones

```bash
alembic revision -m "descripcion corta"   # revisar SIEMPRE el archivo generado
alembic upgrade head
alembic downgrade -1                      # tiene que funcionar
```

- Una migración por PR como máximo.
- Los enums se guardan como `VARCHAR(32)`, no como tipo nativo de Postgres:
  agregar una categoría no requiere migración.
- Para migrar contra Supabase usar el **session pooler** (puerto 5432), no el
  transaction pooler.

---

## 5. Tests

- Correr todo: `pytest`. La cobertura mínima es **60%** (rúbrica) y el gate está
  en `pyproject.toml`. Hoy estamos en ~90%: no bajarlo.
- `tests/unit/` no toca base ni red. `tests/integration/` usa SQLite en memoria.
- Publisher de mentira: `InMemoryEventPublisher`. Para afirmar que un caso de uso
  publicó lo correcto: `publisher.eventos_de(topics.RECLAMO_CREADO)`.
- Los tests generan JWT reales con `crear_token()` de `tests/conftest.py`: la capa
  de seguridad se testea de verdad, no se saltea.
- Nombres de test en español y descriptivos: `test_el_autor_no_puede_adherir`.
  Los comentarios dentro del test, en inglés.
- Todo bug que se arregla entra con un test que falla antes del fix.

---

## 6. Git

### Branches

```
main       # estable, protegida
develop    # integración
feature/G5D-<nro>-descripcion-corta
```

### Commits

**Todos los commits llevan el prefijo `G5D-<nro>`**, donde `<nro>` es el número
de tarjeta del board:

```
G5D-12: agrega endpoint de adhesiones
G5D-13: corrige transicion invalida de RESUELTO a CERRADO
```

- Mensaje en español, imperativo, en minúscula después del prefijo.
- Un commit = un cambio coherente. Nada de `wip` ni `varios fixes`.
- No commitear `.env`, `.venv/`, `coverage.xml` ni `__pycache__`.

### Pull requests

A `develop`, con CI en verde (ruff + tests + migraciones + build de imagen).

---

## 7. Comandos

```bash
# entorno
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e ".[dev]"
copy .env.example .env

# infraestructura local (Redpanda + consola + Postgres)
docker compose up -d redpanda redpanda-init redpanda-console postgres

# base
alembic upgrade head

# correr
uvicorn app.main:app --reload     # API en http://localhost:8000/docs
python -m app.worker              # consumidor de eventos

# calidad
ruff check . --fix
ruff format .
pytest

# token de desarrollo
python scripts/dev_token.py --sub vecino-1 --roles ciudadano
python scripts/dev_token.py --sub operador-1 --roles operador
```

### Slash commands de Claude Code

En `.claude/commands/` hay comandos propios del repo que encapsulan estas mismas
convenciones. Se invocan con `/nombre` en la sesión:

| Comando | Para qué |
| --- | --- |
| `/verificar` | Lint + formato + tests, y arregla lo que falle |
| `/nuevo-endpoint` | Endpoint nuevo respetando el orden de capas |
| `/nuevo-evento` | Evento con contrato, idempotencia, test y doc |
| `/migracion` | Migración de Alembic con el ciclo up/down probado |
| `/commit` | Commits con formato `G5D-<nro>` |
| `/adr` | ADR nuevo con opciones consideradas |
| `/rubrica` | Auditoría del repo contra la rúbrica de la cátedra |

Detalle y cómo agregar uno: [`.claude/commands/README.md`](.claude/commands/README.md).

---

## 8. Decisiones ya tomadas — no re-litigar sin ADR

Están en `docs/adr/`. Si algo de esto se cambia, se escribe un ADR nuevo que
supere al anterior:

| ADR | Decisión |
| --- | --- |
| 0001 | Arquitectura en capas con puertos, no hexagonal completa |
| 0002 | Supabase + SQLAlchemy async + Alembic (no `supabase-py`) |
| 0003 | Envelope propio compatible con CloudEvents |
| 0004 | Publicación post-commit; outbox como deuda registrada |
| 0005 | Naive Bayes propio para categoría + reglas para prioridad |

---

## 9. Integración con los otros grupos

| Grupo | Qué nos da / qué le damos |
| --- | --- |
| 1 — EDA | Define el bus y la convención de topics. Nos alineamos a su contrato. |
| 2 — Login Federado | Emite los JWT. Nosotros solo validamos; nunca emitimos tokens. |
| 4 — Residuos | Consumimos `residuos.contenedor.desbordado` → alta automática. |
| 6 — Emergencias | Consumimos `emergencias.incidente.creado` → re-priorización por zona. |
| 8 — Analítica | Consume nuestros eventos y `GET /api/v1/reclamos/estadisticas`. |

Contratos completos con ejemplos: `docs/eventos.md`.
