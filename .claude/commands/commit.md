---
description: Arma los commits del trabajo pendiente con el formato G5D-<nro>
argument-hint: <nro de tarjeta> [contexto opcional]
allowed-tools: Bash, Read, Glob, Grep
---

Armá los commits del trabajo que está sin commitear.

**Tarjeta / contexto:** $ARGUMENTS

## Pasos

1. Mirá `git status --short` y `git diff` (staged y unstaged) para entender qué
   cambió de verdad. No adivines a partir de los nombres de archivo.
2. Agrupá los cambios en commits **coherentes**: un commit = un cambio con
   sentido propio. Si el trabajo toca varias áreas (dominio, API, eventos,
   tests, docs), separalos.
3. Verificá que el árbol esté limpio antes: corré `ruff check .` y `pytest`. No
   commitees con el gate en rojo salvo que te lo pida explícitamente.

## Formato del mensaje

```
G5D-<nro>: <que hace, en imperativo, minuscula, en español>

Por que se hizo y que decisión hay detrás. Dos o tres párrafos cortos como
máximo. Sin bullets salvo que enumeres cosas de verdad.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

- El prefijo `G5D-<nro>` es **obligatorio en todos los commits** (número de
  tarjeta del board). Si no me lo pasaste, preguntámelo antes de commitear.
- El cuerpo explica el **por qué**, no repite el diff. Quien lea el log en tres
  meses quiere saber la decisión, no la lista de archivos.
- Sin tildes ni `ñ` en el mensaje (evita problemas de encoding entre Windows y
  Linux en la consola).
- Nada de `wip`, `fix`, `varios cambios`.

## Nunca commitear

`.env` · `.venv/` · `coverage.xml` · `__pycache__/` · `*.db`

Están en `.gitignore`, pero verificá igual con `git status` antes de hacer
`git add`. Preferí `git add <rutas explícitas>` sobre `git add -A`.

## Al terminar

Mostrame `git log --oneline` con los commits nuevos. **No hagas push** salvo que
te lo pida.
