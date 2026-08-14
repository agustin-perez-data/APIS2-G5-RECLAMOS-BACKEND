---
description: Escribe un ADR nuevo con la estructura de la casa
argument-hint: <decisión a documentar>
allowed-tools: Read, Write, Edit, Glob, Grep, WebSearch, WebFetch
---

Escribí un ADR para la decisión pedida.

**Decisión:** $ARGUMENTS

## Antes de escribir

1. Leé `docs/adr/README.md` y al menos un ADR existente para calcar el tono.
2. Fijate si alguna decisión ya tomada queda **reemplazada**. Los ADR aceptados
   **no se editan**: si esto supera a uno anterior, marcá el viejo como
   *Reemplazada por NNNN* y explicá qué cambió.
3. Numeración correlativa. Archivo:
   `docs/adr/NNNN-titulo-en-kebab-case.md`.

## Estructura

```markdown
# ADR NNNN — <título>

- **Estado:** Aceptada | Propuesta | Reemplazada por NNNN
- **Fecha:** YYYY-MM-DD
- **Contexto:** Sprint N · Grupo 5

## Contexto
El problema real y las restricciones. Qué pide la rúbrica si aplica.

## Opciones consideradas
### A. <opción>
- ✅ ventaja concreta
- ❌ por qué se descarta

(mínimo tres opciones, una de ellas la elegida, marcada con *(elegida)*)

## Decisión
Qué se adopta y las reglas concretas que se derivan.

## Consecuencias
**Positivas.** / **Negativas.** / **A revisar.**
```

## Reglas

- **Las opciones descartadas son la mitad del valor.** Un ADR con una sola
  opción no es un ADR, es una nota. La rúbrica pide explícitamente que se vean
  las alternativas evaluadas.
- Sé honesto con los contras de lo que elegimos. Si hay deuda técnica, nombrala
  y decí bajo qué condición la vamos a pagar (mirá el ADR 0004 como ejemplo).
- Prosa en español. Concreto, sin relleno.
- Al terminar, agregá la fila a la tabla de `docs/adr/README.md` y, si la
  decisión afecta cómo se escribe código, actualizá la sección 8 de
  `CLAUDE.md`.
