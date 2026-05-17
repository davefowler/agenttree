# Concepts

stagent is built from a small set of types that compose. Understanding them is the difference between "tweaking YAML and hoping" and "knowing what's going to happen."

## The mental model

```
┌─────────────────────────────────────────────────────────────────┐
│                         .stagent.yaml                           │
│                                                                 │
│  roles:   developer, reviewer, ...                              │
│  stages:  code, review, pr, cleanup, ...                        │
│  flows:   default = [setup, code, pr, review, human_review, …]  │
│  hooks:   per-stage; enter, exit, tick                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ loaded once at runner start
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       stagent runner                            │
│                                                                 │
│  ┌──────────┐    ┌────────────┐    ┌────────────┐               │
│  │heartbeat │───▶│task worker │───▶│claude -p   │               │
│  │goroutine │    │goroutine   │    │child       │               │
│  └──────────┘    └────────────┘    └────────────┘               │
│       │               │                                         │
│       │               ▼                                         │
│       │         ┌────────────┐                                  │
│       │         │  hooks     │                                  │
│       │         │  (Go code) │                                  │
│       │         └────────────┘                                  │
│       │               │                                         │
│       └───────────────┼─────────────────────────┐               │
│                       ▼                         ▼               │
│              ┌─────────────────┐       ┌─────────────────┐      │
│              │  SQLite event   │       │  task .md file  │      │
│              │  log (append)   │       │  (sections)     │      │
│              └─────────────────┘       └─────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
                ┌─────────────────────────┐
                │   SQL views: tasks,     │
                │   sessions, stage_      │
                │   progress              │
                └─────────────────────────┘
```

Every interaction goes one direction: config + events → state. Nothing writes to projections directly. Nothing edits past events.

## The pieces

### Flow

An ordered list of stage names. A task picks one flow at creation time and walks through it. The default flow is:

```
setup → code → pr → review → human_review → cleanup
```

You can define additional flows in `.stagent.yaml` (e.g. `quick` for trivial tasks). See [Custom flows](../patterns/custom-flows.md).

### Stage

One step in a flow. Each stage has a **type**:

- **`agent`** — a Claude session does the work. Runs until process exit. Hooks judge whether the work passed.
- **`human`** — paused for human input. Completes via `stagent approve <task>` or via tick hooks that detect an external event (PR merge, etc.).
- **`script`** — fully automated. Runs tick hooks on every heartbeat until they all pass.

See [Stages, flows, hooks](stages-flows-hooks.md).

### Role

Who executes an agent stage. A role has a model (`opus`, `sonnet`, `haiku`), a session-binding scope (`task` or `stage`), and a system prompt loaded from `.stagent/prompts/roles/<name>.md`.

A `(task, role)` pair maps to a Claude session ID; the session is reused (`--resume`) across all stages that share the role on the same task, unless the role is `bound: stage` (fresh session each time). See [Sessions](sessions.md).

### Hook

A deterministic Go function that runs at a known point in a stage's lifecycle (`enter`, `exit`, or `tick`) and returns one of four verdicts:

- **`Pass`** — satisfied; advance if other hooks agree.
- **`NotYet`** — for tick hooks; keep waiting.
- **`Fail`** — retry the stage or fail it.
- **`Redirect(stage, message)`** — route to a chosen stage with a message.

Hooks are how stagent decides if a stage is "done." Agents don't decide.

See [Hooks reference](../configuration/hooks-reference.md) for the full list.

### Event

The unit of state. Every transition (stage entered, session started, hook fired, etc.) appends one row to the SQLite event log. The log is **append-only**, enforced by triggers — no `UPDATE`, no `DELETE`, ever. State corrections happen by appending corrective events.

See [The event log](event-log.md).

### Projection

A SQL view over events. The `tasks` view, `sessions` view, and `stage_progress` view tell you the current state of the world — but they're computed, never written to. Adding a new projection is "write a new view," not "design a new schema."

See [Event schema](../reference/schema.md).

## What's in this section

- **[Stages, flows, hooks](stages-flows-hooks.md)** — the workflow machinery in detail.
- **[The event log](event-log.md)** — why event-sourcing, what's stored, recovery semantics.
- **[Sessions](sessions.md)** — how Claude sessions are scoped and resumed.
