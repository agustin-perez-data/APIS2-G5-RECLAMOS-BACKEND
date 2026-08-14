---
description: Audita el repo contra la rúbrica de la cátedra y lista los gaps
argument-hint: [dimension a auditar, o vacío para todas]
allowed-tools: Bash, Read, Glob, Grep
---

Auditá el estado real del repo contra la rúbrica del TP integrador y decime qué
falta.

**Alcance:** $ARGUMENTS (si está vacío, auditá las 10 dimensiones)

## Rúbrica (100 pts, 10 por dimensión)

| # | Dimensión | Qué se evalúa |
| --- | --- | --- |
| 1 | Diseño de arquitectura | Modularidad interna, separación de responsabilidades, patrones |
| 2 | Modelado y diagramas | 4+1 / C4 / cloud, con coherencia técnica |
| 3 | Seguridad e identidad | JWT, roles, login federado (LDAP), endpoints protegidos |
| 4 | Integración y APIs | REST, GraphQL, middlewares, manejo de errores |
| 5 | Event Driven Architecture | Tópicos, contratos de eventos, pub/sub |
| 6 | Testing | 60% de cobertura (unitarios e integrales), automatizados |
| 7 | DevOps & Cloud | CI/CD, infraestructura como código, despliegue cloud |
| 8 | IA / ML / I+D | Modelos bien aplicados e integrados funcionalmente |
| 9 | UX/UI del módulo | Prototipo funcional (si aplica al backend, evaluá el OpenAPI) |
| 10 | Trabajo en equipo y SCRUM | Git, board, roles, retrospectivas, entregas por sprint |

Requisito transversal: **toda decisión de arquitectura documentada en un ADR**
con las opciones consideradas.

## Cómo auditar

Andá al código, no a la documentación. Para cada dimensión:

1. Buscá la **evidencia concreta** (archivo y línea) de que está cubierta.
2. Verificá que funcione: corré `pytest`, mirá la cobertura real, revisá que el
   workflow de CI tenga los jobs que dice tener.
3. Marcá el estado: **cubierto** / **parcial** / **faltante**.

Sé escéptico con el propio repo. Un README que promete algo no es evidencia; el
código que lo hace, sí. Ejemplos de gaps que hay que detectar y no maquillar:

- Cobertura que pasa el gate pero deja sin testear el camino que importa.
- Endpoints "protegidos" que en realidad no exigen rol.
- Eventos documentados en `docs/eventos.md` que nadie publica.
- Un job de CI que existe pero nunca corrió en verde.
- Despliegue cloud declarado pero sin infraestructura como código real.

## Salida

Una tabla con dimensión → estado → evidencia (archivo:línea) → qué falta, y
después una lista **priorizada** de acciones concretas: qué hacer primero para
ganar más puntos con menos trabajo. Nada de "mejorar el testing": decime qué
test escribir y sobre qué archivo.

Si una dimensión no aplica al backend (la 9, por ejemplo), decilo en vez de
inventar trabajo.
