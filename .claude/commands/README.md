# Repo slash commands

Claude Code commands specific to the Reclamos module. Invoke them by typing
`/name` in a session. They encode the conventions from `CLAUDE.md`, so the code
that comes out is consistent no matter which of us asked for it.

| Command | What it does |
| --- | --- |
| `/verificar` | Runs lint, format and tests, and fixes what breaks. Use it before every PR. |
| `/nuevo-endpoint <description>` | Adds an endpoint respecting the schema → service → repo → router → test order. |
| `/nuevo-evento publicar\|consumir <topic>` | Adds an event with contract, idempotency, test and a `docs/eventos.md` entry. |
| `/migracion <description>` | Generates and **reviews** an Alembic migration, with the upgrade/downgrade cycle actually run. |
| `/commit <nro>` | Builds the commits in `G5D-<nro>` format with a body explaining the why. |
| `/adr <decision>` | Writes a new ADR with considered options and consequences. |
| `/rubrica [dimension]` | Audits the repo against the course rubric and lists prioritised gaps. |

## Language

The command files are written in English, like every comment and docstring in
the repo. What they **produce** keeps the language stated in `CLAUDE.md`: commit
messages, ADRs, OpenAPI `summary`/`description` and error `title` stay in
Spanish. Each command says so where it matters — do not "fix" that.

## Adding one

One `.md` file per command in this folder. The file name is the command name.

```markdown
---
description: One line, this is what shows up in the command list
argument-hint: <what it expects as an argument>
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

The prompt. `$ARGUMENTS` is replaced by whatever the user typed after the
command; `$1`, `$2`… by each positional argument.
```

Commands are **project-scoped**: they live in the repo, they are versioned, and
they apply to the whole team. For a personal one, use `~/.claude/commands/`.

Different from *skills* (`.claude/skills/<name>/SKILL.md`), which the model
invokes on its own whenever it believes they apply. Here we prefer explicit
commands: the team decides when each flow fires.
