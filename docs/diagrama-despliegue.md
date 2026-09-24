# Diagrama de despliegue — Backend de Reclamos (Grupo 5)

Este documento describe dónde corre cada parte del sistema y cómo llega el código
a producción. Los diagramas están en Mermaid, así que GitHub los dibuja directo.

## 1. Arquitectura de despliegue

```mermaid
flowchart LR
    U["Usuarios<br/>ciudadano / operador"]

    subgraph Vercel["Vercel"]
        FE["Frontend web"]
    end

    subgraph Railway["Railway"]
        API["API de Reclamos<br/>FastAPI en Docker<br/>configurada con railway.json"]
    end

    subgraph Supabase["Supabase"]
        DB[("PostgreSQL<br/>RLS activado")]
    end

    JIRA["Jira Cloud<br/>proyecto REC"]
    AUTH["Grupo 2<br/>Login federado (JWT)"]
    KAFKA["Kafka / Redpanda<br/>deshabilitado (KAFKA_ENABLED=false)"]

    U -->|HTTPS| FE
    FE -->|"HTTPS · API REST /api/v1"| API
    API -->|"SQL · Transaction Pooler :6543"| DB
    API -->|"crea un ticket por cada reclamo nuevo"| JIRA
    AUTH -.->|"JWT"| API
    API -.->|"eventos"| KAFKA
```

**Referencias**

- Las flechas punteadas son integraciones opcionales o todavía no activas: Kafka
  está apagado en producción, y el login del Grupo 2 convive con el login de prueba
  (`/api/v1/auth/dev/login`) durante la Entrega 1.
- La integración con Jira se activa con `JIRA_ENABLED=true` y necesita
  `JIRA_URL`, `JIRA_EMAIL` y `JIRA_API_TOKEN`.
- Toda la configuración sensible vive en variables de entorno de Railway, no en el
  repositorio.
- La configuración de despliegue de Railway está versionada en el repositorio
  (`railway.json`, infraestructura como código), con un healthcheck en
  `/health/ready`: Railway solo le pasa el tráfico a un deploy nuevo cuando ese
  endpoint responde bien, y si sale roto sigue atendiendo la versión anterior.

## 2. Pipeline de CI/CD

```mermaid
flowchart LR
    DEV["Desarrollador"] -->|"push a rama / Pull Request"| GH["GitHub<br/>repo del backend"]
    DBOT["Dependabot"] -->|"PRs semanales de dependencias"| GH

    subgraph CI["GitHub Actions · ci-backend.yml<br/>(cualquier rama y PR)"]
        direction TB
        L["Lint + tests<br/>ruff, pytest, cobertura"]
        M["Migraciones Alembic<br/>contra PostgreSQL 16"]
        D["Docker build"]
        S["Job SonarCloud"]
        L --> S
    end

    subgraph CD["GitHub Actions · cd-backend.yml<br/>(solo push a main)"]
        direction TB
        B["Build"] --> MIG["Migraciones en Supabase"] --> DEP["Deploy a Railway<br/>Railway CLI"] --> SM["Smoke test<br/>GET /health/ready"]
    end

    GH --> CI
    GH -->|"merge a main<br/>PR + aprobación + checks en verde"| CD

    S --> SONAR["SonarCloud<br/>análisis y cobertura"]
    MIG --> SUPA[("Supabase<br/>PostgreSQL")]
    DEP --> RW["Railway<br/>API en producción"]
    SM -.->|"verifica que responda"| RW
    RJ["railway.json<br/>infraestructura como código<br/>healthcheck /health/ready"] -->|"configura el deploy"| RW

    KA["Keepalive de Supabase<br/>cada 12 horas"] --> SUPA
```

**Referencias**

- La rama `main` está protegida: nadie sube directo, hace falta un Pull Request
  aprobado y los checks `Lint + tests` y `Alembic against PostgreSQL` en verde.
- El CD aplica las migraciones en Supabase **antes** de desplegar en Railway, y si
  el smoke test no recibe respuesta de `/health/ready`, el run queda en rojo.
- El workflow de keepalive consulta la base cada 12 horas para que el plan gratuito
  de Supabase no la pause.