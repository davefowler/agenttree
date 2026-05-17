# stagent

Staged workflow for AI agents. An event-sourced state machine that drives Claude sessions through configurable stages.

## What it is

A `stagent` **flow** is an ordered list of **stages**. Each stage is one of:

- **`agent`** — a Claude session does the work.
- **`human`** — paused for human review (or auto-completes when an external signal arrives, like a PR merge).
- **`script`** — automated by the runner (CI watch, git ops, cleanup).

A **task** is a single markdown file (`tasks/<id>-<slug>.md`) with sections that represent stage outputs. Stages fill in their sections; hooks validate by checking checkboxes and section content. You write the task spec yourself (in Cursor, vim, whatever) — stagent runs the **execution loop** (code → CI → review → merge), not the planning loop.

Everything that happens is appended to a SQLite **event log**. The current state of any task is a SQL view over that log.

## Why use it

- **One mental model.** Every workflow is the same shape — a flow of stages, validated by hooks. No special "research" mode vs. "implement" mode vs. "review" mode.
- **No self-grading.** Agents work, then exit. Deterministic Go hooks decide whether the work passes. The agent never claims completion to itself.
- **Crash-safe by construction.** The runner can die mid-stage and the next start picks up where it left off. State lives in events, not memory.
- **Audit trail built in.** Every transition is an immutable event. "Why did this task take seven rounds?" → read the log.
- **Composable.** Hooks are an interface; add a new one in ~20 lines + a test. Flows are just YAML lists. Customize without forking.

## Design tenets

1. **One source of truth.** Events. Everything else is a projection.
2. **One way to do each thing.** No alternate paths, no compatibility shims.
3. **Configuration in YAML. State in SQLite. Documents on disk.** Each tool to its strength.
4. **The agent signals done by exiting; the runner judges with hooks.** Agents never run hooks or self-declare completion. Process exit triggers deterministic evaluation; failure resumes the agent with structured feedback.
5. **Append-only, always.** No UPDATE, no DELETE, ever. Enforced by SQLite triggers. State corrections happen by appending corrective events.
6. **Crash-safe by construction.** Process death anywhere never corrupts state — at worst, the next heartbeat retries.

## Getting started

- [**Quickstart**](quickstart.md) — install, init, run your first task.
- [**Concepts**](concepts/index.md) — the mental model: stages, flows, hooks, the event log.
- [**Configuration**](configuration/index.md) — the `.stagent.yaml` format and the task file format.
- [**Patterns**](patterns/review-loop.md) — worked examples for common workflows.
- [**Reference**](reference/cli.md) — every CLI command, every hook, every event type.

## How it differs from [agenttree](https://github.com/davefowler/agenttree)

Same idea, rewritten:

- **Go** instead of Python — strong types, single binary, native concurrency for the heartbeat.
- **SQLite event log + views** instead of YAML files — atomic writes, queryable, no merge conflicts.
- **Direct `claude -p`** instead of tmux orchestration — sessions tracked by ID, not by terminal.
- **SwiftUI viewer** reads the SQLite file directly, push-updated via WAL file watching.

## Implementation notes

The doc site you're reading is user-facing — how to use stagent. The engineer-facing **implementation notes** live in [`notes/`](https://github.com/davefowler/stagent/tree/main/notes) in the repository:

- [`notes/architecture.md`](https://github.com/davefowler/stagent/blob/main/notes/architecture.md) — types, lifecycle, design rationale.
- [`notes/schema.md`](https://github.com/davefowler/stagent/blob/main/notes/schema.md) — event log + views + migration approach.
- [`notes/config.md`](https://github.com/davefowler/stagent/blob/main/notes/config.md) — `.stagent.yaml` format rationale.

If you're considering contributing or you want to understand "why is it built this way?", start there.

## Status

Pre-alpha. The event log + state machine is milestone one. The SwiftUI viewer is milestone two.
