---
description: Audits the repo against the course rubric and lists the gaps
argument-hint: [dimension to audit, or empty for all]
allowed-tools: Bash, Read, Glob, Grep
---

Audit the repo's real state against the course rubric and tell me what is
missing.

**Scope:** $ARGUMENTS (if empty, audit all ten dimensions)

## Rubric (100 pts, 10 per dimension)

| # | Dimension | What is graded |
| --- | --- | --- |
| 1 | Diseño de arquitectura | Internal modularity, separation of concerns, patterns |
| 2 | Modelado y diagramas | 4+1 / C4 / cloud, technically coherent |
| 3 | Seguridad e identidad | JWT, roles, federated login (LDAP), protected endpoints |
| 4 | Integración y APIs | REST, GraphQL, middlewares, error handling |
| 5 | Event Driven Architecture | Topics, event contracts, pub/sub |
| 6 | Testing | 60% coverage (unit and integration), automated |
| 7 | DevOps & Cloud | CI/CD, infrastructure as code, cloud deployment |
| 8 | IA / ML / I+D | Models properly applied and functionally integrated |
| 9 | UX/UI del módulo | Working prototype (for a backend, grade the OpenAPI page) |
| 10 | Trabajo en equipo y SCRUM | Git, board, roles, retrospectives, sprint deliveries |

Cross-cutting requirement: **every architecture decision documented in an ADR**
with the options that were considered.

## How to audit

Go to the code, not to the documentation. For each dimension:

1. Find the **concrete evidence** that it is covered (file and line).
2. Verify it actually works: run `pytest`, look at real coverage, check that the
   CI workflow has the jobs it claims to have.
3. Mark the status: **cubierto** / **parcial** / **faltante**.

Be sceptical of this repo. A README that promises something is not evidence; the
code that does it is. Gaps worth catching instead of glossing over:

- Coverage that clears the gate while leaving the path that matters untested.
- "Protected" endpoints that do not actually require a role.
- Events documented in `docs/eventos.md` that nobody publishes.
- A CI job that exists but has never gone green.
- Cloud deployment claimed with no real infrastructure as code.

## Output

Write the report in **Spanish**. A table of dimension → status → evidence
(`file:line`) → what is missing, followed by a **prioritised** list of concrete
actions: what to do first to gain the most points for the least work. No
"improve testing": name the test to write and the file it covers.

If a dimension does not apply to the backend (number 9, for instance), say so
instead of inventing work.
