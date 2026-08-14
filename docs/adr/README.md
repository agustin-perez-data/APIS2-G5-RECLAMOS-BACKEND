# Architecture Decision Records

Decisiones de arquitectura del módulo de Reclamos (Grupo 5). Cada una registra
el contexto, las opciones que se evaluaron y por qué se descartaron.

| # | Decisión | Estado |
| --- | --- | --- |
| [0001](0001-arquitectura-en-capas.md) | Arquitectura en capas con puertos | Aceptada |
| [0002](0002-persistencia-supabase.md) | Supabase con SQLAlchemy async + Alembic | Aceptada |
| [0003](0003-contratos-de-eventos.md) | Envelope propio compatible con CloudEvents | Aceptada |
| [0004](0004-publicacion-de-eventos.md) | Publicación post-commit, outbox como deuda | Aceptada |
| [0005](0005-clasificacion-automatica.md) | Naive Bayes propio + reglas de prioridad | Aceptada |

## Cómo agregar uno

Numeración correlativa, nunca se edita un ADR aceptado: si la decisión cambia,
se escribe uno nuevo que lo supere y se marca el viejo como *Reemplazada por
NNNN*.

Estructura: **Contexto** → **Opciones consideradas** (con el ✅/❌ de cada una)
→ **Decisión** → **Consecuencias** (positivas, negativas y qué queda por
revisar).
