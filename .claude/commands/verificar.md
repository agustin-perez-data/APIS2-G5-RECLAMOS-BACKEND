---
description: Runs lint, format and tests, and fixes whatever breaks
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

Run the repo's full quality gate and leave everything green.

## Steps

1. **Lint**: `ruff check .` — on errors, run `ruff check . --fix` and review that
   the autofixes make sense. Watch out for `SIM905`: if it touches the stopword
   list in `app/ml/text.py`, keep the `# fmt: off` block that keeps it readable.
2. **Format**: `ruff format .`, then `ruff format --check .`.
3. **Tests**: `pytest`. The coverage gate is 60% (course rubric) and lives in
   `pyproject.toml`.

On Windows the venv interpreter is `.venv\Scripts\python.exe`; on Linux/Mac it is
`.venv/bin/python`. Use it as `<python> -m ruff` / `<python> -m pytest` when the
binaries are not on the PATH.

## When done

Report, in this order:

- What failed and what you fixed, with file and line.
- Final test count and coverage.
- If coverage dropped below what `CLAUDE.md` states (~90%), say so explicitly and
  point at which module lost coverage.

If something cannot be fixed without a design decision, **do not patch over it**:
explain the problem and the options. Never lower the coverage threshold, and
never add a `# noqa` just to silence the linter without justifying it in a
comment.

$ARGUMENTS
