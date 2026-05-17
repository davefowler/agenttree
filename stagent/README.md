# stagent

Staged workflow for AI agents. An event-sourced state machine that drives Claude sessions through configurable stages.

## What

A `stagent` workflow is a **flow** — an ordered list of **stages**. Each stage is one of:

- **`agent`** — a Claude session does the work
- **`human`** — paused for human review (or auto-completes when an external signal arrives, like a PR merge)
- **`script`** — automated by the runner (CI watch, git ops, cleanup)

A **task** is a single markdown file (`tasks/<id>-<slug>.md`) with sections that represent stage outputs. Stages fill in their sections; hooks validate by checking checkboxes and section content. The user writes the task spec themselves (in Cursor, vim, whatever) — stagent runs the **execution loop** (code → CI → review → merge), not the planning loop.

Everything that happens is appended to a SQLite **event log**. The current state of any task is a SQL view over that log.

## Why not [agenttree](https://github.com/davefowler/agenttree)?

Same idea, rewritten:

- **Go** instead of Python — strong types, single binary, native concurrency for the heartbeat
- **SQLite event log + views** instead of YAML files — atomic writes, queryable, no merge conflicts
- **Direct `claude -p`** instead of tmux orchestration — sessions tracked by ID, not by terminal
- **SwiftUI viewer** reads the SQLite file directly, push-updated via WAL file watching

## Design tenets

1. **One source of truth.** Events. Everything else is a projection.
2. **One way to do each thing.** No alternate paths, no compatibility shims.
3. **Configuration in YAML. State in SQLite. Documents on disk.** Each tool to its strength.
4. **The agent signals done by exiting; the heartbeat judges with hooks.** Agents never run hooks or self-declare completion. Process exit triggers deterministic evaluation; failure resumes the agent with structured feedback.
5. **Append-only, always.** No UPDATE, no DELETE, ever. Enforced by SQLite triggers. State corrections happen by appending corrective events.
6. **Crash-safe by construction.** Process death anywhere never corrupts state — at worst, the next heartbeat retries.

## Quickstart

```bash
go install github.com/davefowler/stagent@latest    # brew tap once there's a v0.1
cd my-project
stagent init                              # writes .stagent.yaml and scaffolds .stagent/

# Option A: write your spec in your editor first, then register it.
stagent new tasks/fix-login.md

# Option B: start from the template, fill it in after.
stagent new "Fix login redirect bug"

stagent run                               # starts the runner (per-repo, foreground)
stagent status                            # show all tasks and stages
```

## Layout

```
.stagent.yaml                          # roles, stages, flows, hooks, commands

tasks/                                 # COMMITTED — one markdown file per task
  001-fix-login-redirect.md            # sections within = stage outputs
  002-add-user-export.md

.stagent/
  prompts/                             # COMMITTED — workflow definition
    roles/<role>.md                    #   role system prompts (sent once per session)
    stages/<stage>.md                  #   stage user prompts (sent on every entry)
  templates/
    task.md                            # COMMITTED — optional template for new task files

  stagent.db                           # GITIGNORED — per-dev event log (SQLite, WAL)
  runner.pid                           # GITIGNORED — per-dev runner liveness
```

`.gitignore` snippet:

```
.stagent/stagent.db*
.stagent/runner.pid
.worktrees/
```

## Docs

Two doc surfaces, intentionally separate:

**User-facing docs** live in [`docs/`](./docs/) and are built with MkDocs. To view locally:

```bash
pip install mkdocs-material pymdown-extensions
mkdocs serve
```

Then open <http://127.0.0.1:8000>. The site covers concepts, configuration, hooks, CLI reference, and worked patterns.

**Implementation notes** — the "why we built it this way" engineer-facing notes — live in [`notes/`](./notes/):

- [notes/architecture.md](./notes/architecture.md) — types, lifecycle, design rationale
- [notes/schema.md](./notes/schema.md) — event log + views + migration approach
- [notes/config.md](./notes/config.md) — `.stagent.yaml` format rationale

If you're a contributor or you want to understand "why is it built this way?", start in `notes/`. If you're a user trying to get tasks running, start in `docs/`.

## Status

Pre-alpha. The event log + state machine is milestone one. The SwiftUI viewer is milestone two.
