# stagent

Staged workflow for AI agents. An event-sourced state machine that drives Claude sessions through configurable stages.

## What

A `stagent` workflow is a **flow** — an ordered list of **stages**. Each stage is one of:

- **`agent`** — a Claude session does the work
- **`human`** — paused for human review (or auto-completes when an external signal arrives, like a PR merge)
- **`script`** — automated by the daemon (CI watch, git ops, cleanup)

A **task** is a single markdown file (`tasks/<id>-<slug>.md`) with sections that represent stage outputs. Stages fill in their sections; hooks validate by checking checkboxes and section content. The user writes the task spec themselves (in Cursor, vim, whatever) — stagent runs the **execution loop** (code → CI → review → merge), not the planning loop.

Everything that happens is appended to a SQLite **event log**. The current state of any task is a SQL view over that log.

## Why not [agenttree](https://github.com/davefowler/agenttree)?

Same idea, rewritten:

- **Go** instead of Python — strong types, single binary, native concurrency for the heartbeat
- **SQLite event log + views** instead of YAML files — atomic writes, queryable, no merge conflicts
- **Direct `claude -p`** instead of tmux orchestration — sessions tracked by ID, not by terminal
- **SwiftUI viewer** reads the SQLite file directly, push-updated via a heartbeat sentinel

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
# write your task spec in your editor of choice, save as tasks/fix-login.md
stagent task new tasks/fix-login.md       # register the existing file
stagent run                               # starts the daemon (per-repo, foreground)
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
  daemon.pid                           # GITIGNORED — per-dev daemon liveness
```

`.gitignore` snippet:

```
.stagent/stagent.db*
.stagent/daemon.pid
.worktrees/
```

## Docs

- [ARCHITECTURE.md](./ARCHITECTURE.md) — types, lifecycle, design
- [SCHEMA.md](./SCHEMA.md) — event log + views
- [CONFIG.md](./CONFIG.md) — `.stagent.yaml` format

## Status

Pre-alpha. The event log + state machine is milestone one. The SwiftUI viewer is milestone two.
