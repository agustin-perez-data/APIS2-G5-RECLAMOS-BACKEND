# Vista de desarrollo

Cómo está organizado el código, qué puede depender de qué, y qué recorrido hace
un cambio desde la rama de quien lo escribe hasta producción. Es la vista de
quien programa en el repositorio.

## Paquetes y regla de dependencias

Las dependencias apuntan hacia adentro: la entrada depende del negocio, el
negocio depende de abstracciones, y el dominio no depende de nadie.

```mermaid
flowchart TB
    subgraph entrada["Entrada"]
        api["app/api<br/>routers, deps, errors"]
        worker["app/worker.py<br/>consumidor Kafka (solo local)"]
    end

    subgraph aplicacion["Aplicación"]
        services["app/services<br/>casos de uso y transacciones"]
        handlers["app/events/handlers.py<br/>reacciones a eventos entrantes"]
        schemas["app/schemas<br/>DTO de entrada y salida"]
    end

    subgraph dominio["Dominio"]
        domain["app/domain<br/>enums, geo, barrios"]
        ml["app/ml<br/>naive_bayes, similitud, text,<br/>corpus, evaluacion"]
        contracts["app/events/contracts.py y topics.py<br/>sobre y payloads"]
    end

    subgraph infraestructura["Infraestructura"]
        repositories["app/repositories<br/>consultas"]
        models["app/db<br/>modelos ORM y sesión"]
        adaptadores["app/events/gateway.py y producer.py<br/>adaptadores del bus"]
        integrations["app/integrations<br/>Jira"]
    end

    core["app/core<br/>config, security, logging, rate_limit, exceptions"]

    api --> services
    api --> schemas
    api --> handlers
    worker --> handlers
    handlers --> services
    handlers --> contracts
    services --> domain
    services --> ml
    services --> contracts
    services --> repositories
    services --> adaptadores
    services --> integrations
    schemas --> domain
    repositories --> models
    models --> domain
    adaptadores --> contracts
    contracts --> domain

    api -.-> core
    services -.-> core
    adaptadores -.-> core
    integrations -.-> core
```

### Reglas que el diagrama no muestra

| Regla | Dónde se ve |
| --- | --- |
| Los routers no contienen lógica de negocio ni tocan la sesión | `app/api/v1/` |
| El servicio es el dueño de la transacción: el repositorio hace `flush()` y nunca `commit()` | `app/repositories/` |
| En servicios y dominio se levantan excepciones de dominio, no `HTTPException`; la traducción a `problem+json` vive en `app/api/errors.py` | `app/core/exceptions.py` |
| El servicio depende del puerto `EventPublisher`, no del gateway ni de Kafka | `app/events/producer.py` |
| Todo endpoint declara su identidad con `UsuarioDep`, `StaffDep` o `AdminDep`; las excepciones están documentadas | `CLAUDE.md` |
| Toda migración que crea una tabla activa RLS como última línea del `upgrade` | `alembic/versions/` |
| `app/domain` no importa de ningún otro paquete de `app/` | `app/domain/` |

Estas reglas están escritas en `CLAUDE.md` y se revisan en cada pull request. No
hay todavía un chequeo automático de imports entre capas.

## Organización del repositorio

```
app/                 código de la aplicación (ver C4 nivel 3)
alembic/versions/    13 migraciones, de 0001 a 0013
tests/unit/          lógica pura: dominio, clasificador, contratos, seguridad
tests/integration/   API y servicios contra una base real
docs/adr/            19 decisiones de arquitectura
docs/arquitectura/   estas vistas
docs/avro/           esquemas de los cinco eventos publicados
docs/ml/             evaluación y ficha del clasificador
docs/eventos.md      contrato de eventos, campo por campo
scripts/             utilidades (tipos del gateway, evaluación del clasificador)
.github/workflows/   CI, CD y tareas programadas
```

## Del commit a producción

```mermaid
flowchart LR
    dev["Rama de trabajo<br/>feature/G5D-n o fix/G5D-n"]
    pr["Pull request<br/>a develop"]
    develop["develop"]
    main["main<br/>(protegida)"]

    subgraph ci["CI Backend: en cada push y en cada PR"]
        direction TB
        lint["Lint + tests<br/>ruff check, ruff format,<br/>pytest con cobertura"]
        mig["Alembic contra PostgreSQL<br/>upgrade head y downgrade base"]
        sonar["SonarCloud<br/>calidad y cobertura"]
        docker["Imagen Docker<br/>docker build"]
        lint --> sonar
    end

    subgraph cd["CD Backend: en cada push a main"]
        direction TB
        build["Compila la imagen"]
        migrar["Migraciones contra Supabase<br/>alembic upgrade head"]
        deploy["Deploy en Render<br/>y espera a que quede activo"]
        smoke["Smoke test<br/>contra /health"]
        build --> migrar --> deploy --> smoke
    end

    prod(["Producción"])

    dev --> pr
    pr -->|"dispara"| ci
    pr -->|"review y merge"| develop
    develop -->|"PR de release"| main
    main -->|"dispara"| cd
    smoke --> prod
```

### Qué garantiza cada etapa

| Etapa | Qué verifica | Qué pasa si falla |
| --- | --- | --- |
| Lint + tests | Estilo, formato y la suite completa con un mínimo de 60 % de cobertura (`--cov-fail-under=60`) | El PR queda en rojo |
| Alembic contra PostgreSQL | Que las migraciones suben y bajan enteras contra un PostgreSQL real, no contra SQLite | El PR queda en rojo |
| SonarCloud | Bugs, vulnerabilidades y deuda sobre el reporte de cobertura | Informa en el PR |
| Imagen Docker | Que el `Dockerfile` compila | El PR queda en rojo |
| Migraciones contra Supabase | Corren **antes** del deploy | El deploy no arranca: la base no queda adelantada respecto del código |
| Smoke test | Que la versión nueva responde en `/health` | El pipeline queda en rojo aunque el deploy haya salido |

### Tareas programadas

| Workflow | Frecuencia | Para qué |
| --- | --- | --- |
| `keepalive-render.yml` | Cada 10 minutos | Evita que el plan gratuito de Render duerma el servicio |
| `keepalive-supabase.yml` | Cada 12 horas | Evita que Supabase pause el proyecto por inactividad |

Dependabot abre los pull requests de actualización de dependencias y de acciones.

## Estrategia de pruebas

| Nivel | Dónde | Contra qué corre |
| --- | --- | --- |
| Unitarias | `tests/unit/` | Sin base ni red: dominio, clasificador, contratos, validación de JWT |
| Integración | `tests/integration/` | La API completa con SQLite en memoria y el publisher en memoria |
| Calidad del modelo | `tests/unit/test_calidad_clasificador.py` | Dos conjuntos de prueba apartados; falla si el clasificador baja de su piso (ADR 0019) |
| Integración con PostgreSQL | `tests/integration/test_emergencia_via_postgres.py` y el job de Alembic | PostgreSQL real, para lo que SQLite no reproduce (concurrencia, tipos) |

Los adaptadores en memoria del bus y de tickets son los que permiten que la suite
entera corra sin broker, sin gateway y sin Jira.

## Entorno local

`docker-compose.yml` levanta el sistema completo sin depender de nada externo:

| Servicio | Para qué |
| --- | --- |
| `redpanda` y `redpanda-init` | Broker compatible con Kafka y creación de tópicos |
| `redpanda-console` | Inspección de los mensajes |
| `postgres` | Base local |
| `api` | La API |
| `worker` | El consumidor de Kafka y el cierre automático por vencimiento |

En local los eventos van por Kafka y en producción por el gateway. El cambio es
de configuración (`GATEWAY_ENABLED`, `KAFKA_ENABLED`): el servicio y los
handlers son los mismos.

## Convenciones

- **Ramas:** `feature/G5D-<n>-descripcion`, `fix/G5D-<n>-descripcion`,
  `docs/G5D-<n>-descripcion`.
- **Commits:** prefijo con la tarjeta, en español y en imperativo.
- **Código:** nombres de dominio en español, comentarios en inglés; `ruff` como
  linter y formateador.
- **Decisiones:** toda decisión de arquitectura lleva su ADR con las opciones
  consideradas.

## Deuda visible en esta vista

- **No hay infraestructura como código.** El servicio de Render y sus variables
  se configuran desde el panel o la API; no hay un `render.yaml` versionado.
- **La mayoría de los tests de integración corre sobre SQLite** y producción es
  PostgreSQL. El job de Alembic y el test de concurrencia cubren parte de la
  diferencia, no toda.
- **`railway.json` sigue en la raíz** aunque el deploy es a Render.

## Decisiones relacionadas

- [ADR 0001](../adr/0001-arquitectura-en-capas.md): capas con puertos.
- [ADR 0002](../adr/0002-persistencia-supabase.md): Alembic y RLS.
