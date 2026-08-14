---
description: Writes a new ADR using the house structure
argument-hint: <decision to document>
allowed-tools: Read, Write, Edit, Glob, Grep, WebSearch, WebFetch
---

Write an ADR for the requested decision.

**Decision:** $ARGUMENTS

The ADR itself is written in **Spanish** — it is a course deliverable and has to
match the existing ones in `docs/adr/`.

## Before writing

1. Read `docs/adr/README.md` and at least one existing ADR to match the tone.
2. Check whether an accepted decision gets **superseded**. Accepted ADRs are
   **never edited**: if this one supersedes an earlier decision, mark the old one
   as *Reemplazada por NNNN* and explain what changed.
3. Sequential numbering. File: `docs/adr/NNNN-titulo-en-kebab-case.md`.

## Structure

```markdown
# ADR NNNN — <title>

- **Estado:** Aceptada | Propuesta | Reemplazada por NNNN
- **Fecha:** YYYY-MM-DD
- **Contexto:** Sprint N · Grupo 5

## Contexto
The real problem and its constraints. What the rubric asks for, when relevant.

## Opciones consideradas
### A. <option>
- ✅ concrete advantage
- ❌ why it is discarded

(at least three options, one of them the chosen one, marked *(elegida)*)

## Decisión
What gets adopted and the concrete rules that follow from it.

## Consecuencias
**Positivas.** / **Negativas.** / **A revisar.**
```

## Rules

- **The discarded options are half the value.** An ADR with a single option is
  not an ADR, it is a note. The rubric explicitly asks to see the alternatives
  that were evaluated.
- Be honest about the downsides of what we chose. If it creates technical debt,
  name it and state the condition under which we will pay it (see ADR 0004 as
  the example).
- Prose in Spanish. Concrete, no filler.
- When done, add the row to the table in `docs/adr/README.md` and, if the
  decision changes how code is written, update section 8 of `CLAUDE.md`.
