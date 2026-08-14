---
description: Corre lint, formato y tests, y arregla lo que falle
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Ejecutá el gate de calidad completo del repo y dejá todo en verde.

## Pasos

1. **Lint**: `ruff check .` — si hay errores, corré `ruff check . --fix` y revisá
   que los autofixes tengan sentido. Ojo con `SIM905`: si toca la lista de
   stopwords de `app/ml/text.py`, respetá el bloque `# fmt: off` que la mantiene
   legible.
2. **Formato**: `ruff format .` y después `ruff format --check .`.
3. **Tests**: `pytest`. El gate de cobertura es 60% (rúbrica) y está en
   `pyproject.toml`.

En Windows el intérprete del venv es `.venv\Scripts\python.exe`; en Linux/Mac es
`.venv/bin/python`. Usalo como `<python> -m ruff` / `<python> -m pytest` si los
binarios no están en el PATH.

## Al terminar

Reportá en este orden:

- Qué falló y qué arreglaste (con el archivo y la línea).
- El número de tests y la cobertura final.
- Si la cobertura bajó respecto de lo que dice `CLAUDE.md` (~90%), decilo
  explícitamente y señalá qué módulo perdió cobertura.

Si algo no se puede arreglar sin una decisión de diseño, **no lo parchees**:
explicá el problema y las opciones. Nunca bajes el umbral de cobertura ni
agregues `# noqa` para hacer callar al linter sin justificarlo en un comentario.

$ARGUMENTS
