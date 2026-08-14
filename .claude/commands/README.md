# Slash commands del repo

Comandos de Claude Code propios del módulo de Reclamos. Se invocan escribiendo
`/nombre` en la sesión y encapsulan las convenciones de `CLAUDE.md`, así el
código que sale es consistente sin importar quién del equipo lo pida.

| Comando | Para qué |
| --- | --- |
| `/verificar` | Corre lint, formato y tests, y arregla lo que falle. Úsalo antes de cada PR. |
| `/nuevo-endpoint <descripción>` | Agrega un endpoint respetando el orden schema → servicio → repo → router → test. |
| `/nuevo-evento publicar\|consumir <topic>` | Agrega un evento con contrato, idempotencia, test y entrada en `docs/eventos.md`. |
| `/migracion <descripción>` | Genera y **revisa** una migración de Alembic, con el ciclo upgrade/downgrade probado. |
| `/commit <nro>` | Arma los commits con el formato `G5D-<nro>` y cuerpo explicando el porqué. |
| `/adr <decisión>` | Escribe un ADR nuevo con opciones consideradas y consecuencias. |
| `/rubrica [dimensión]` | Audita el repo contra la rúbrica de la cátedra y lista los gaps priorizados. |

## Agregar uno nuevo

Un archivo `.md` por comando en esta carpeta. El nombre del archivo es el nombre
del comando.

```markdown
---
description: Una línea, es lo que se ve en el listado de comandos
argument-hint: <qué espera como argumento>
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

El prompt. `$ARGUMENTS` se reemplaza por lo que el usuario escribió después del
comando; `$1`, `$2`… por cada argumento posicional.
```

Los comandos son **project-scoped**: viven en el repo, se versionan y valen para
todo el equipo. Si querés uno solo para vos, va en `~/.claude/commands/`.

Distinto de los *skills* (`.claude/skills/<nombre>/SKILL.md`), que los invoca el
modelo solo cuando cree que aplican. Acá preferimos comandos explícitos: el
equipo decide cuándo se dispara cada flujo.
