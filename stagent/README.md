# stagent

Staged workflow for AI agents. An event-sourced state machine that drives Claude sessions through configurable stages.

## What

A `stagent` workflow is a **flow** — an ordered list of **stages**. Each stage is one of:

- **`agent`** — a Claude session does the work
- **`human`** — paused for human review
- **`heartbeat`** — automated by the daemon (CI watch, git ops, container cleanup)

A **task** moves through the flow one stage at a time. Each stage owns an output artifact (a markdown file), has validation **hooks**, and signals completion via a checked `stage_complete` checkbox.

Everything that happens is appended to an **event log**. The current state of any task is a SQL view over that log.

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
stagent init                  # writes .stagent.yaml and creates .stagent/
stagent task new "Fix login redirect bug"
stagent run                   # starts the heartbeat daemon (per-repo, foreground)
stagent status                # show all tasks and stages
```

## Layout

```
.stagent.yaml         # roles, stages, flows, hooks, commands
.stagent/
  stagent.db          # SQLite event log (gitignored)
  daemon.pid          # liveness (gitignored)
  tasks/<id>/         # markdown artifacts per task
    spec.md
    plan.md
    review.md
```

## Docs

- [ARCHITECTURE.md](./ARCHITECTURE.md) — types, lifecycle, design
- [SCHEMA.md](./SCHEMA.md) — event log + views
- [CONFIG.md](./CONFIG.md) — `.stagent.yaml` format

## Status

Pre-alpha. The event log + state machine is milestone one. The SwiftUI viewer is milestone two.
