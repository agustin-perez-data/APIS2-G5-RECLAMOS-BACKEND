---
description: Builds the commits for pending work using the G5D-<nro> format
argument-hint: <board card number> [optional context]
allowed-tools: Bash, Read, Glob, Grep
---

Build the commits for whatever is currently uncommitted.

**Card / context:** $ARGUMENTS

## Steps

1. Look at `git status --short` and `git diff` (staged and unstaged) to
   understand what actually changed. Do not guess from file names.
2. Group the changes into **coherent** commits: one commit = one change that
   stands on its own. If the work spans several areas (domain, API, events,
   tests, docs), split them.
3. Check the tree is clean first: run `ruff check .` and `pytest`. Do not commit
   with the gate red unless explicitly told to.

## Message format

The commit message itself is written in **Spanish** — it has to match the
existing history:

```
G5D-<nro>: <what it does, imperative, lowercase, in Spanish>

Why it was done and the decision behind it. Two or three short paragraphs at
most. No bullets unless you are genuinely enumerating things.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

- The `G5D-<nro>` prefix is **mandatory on every commit** (board card number). If
  it was not provided, ask for it before committing.
- The body explains the **why**, it does not restate the diff. Whoever reads the
  log in three months wants the decision, not the file list.
- No accents or `ñ` in the message (avoids encoding trouble between Windows and
  Linux terminals).
- Never `wip`, `fix`, or `varios cambios`.

## Never commit

`.env` · `.venv/` · `coverage.xml` · `__pycache__/` · `*.db`

They are in `.gitignore`, but verify with `git status` before `git add` anyway.
Prefer `git add <explicit paths>` over `git add -A`.

## When done

Show me `git log --oneline` with the new commits. **Do not push** unless asked.
