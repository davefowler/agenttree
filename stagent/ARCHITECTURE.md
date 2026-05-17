# Architecture

## Design philosophy

`stagent` is built around three rules that the rest of the design falls out of:

1. **An event log is the only persisted state.** Tasks, stages-in-progress, sessions — none of these are tables you write to. They are SQL views over the event log.
2. **The agent signals completion by exiting; the heartbeat decides if the work passes.** Hooks are deterministic Go code that run on process exit. Pass → stage completes. Fail → agent is resumed with the hook errors prepended to its next prompt. The agent never runs hooks, never self-judges.
3. **Configuration is YAML, state is SQLite, documents are markdown.** Each is read or written by the tool best suited to it.

Everything below derives from these rules.

## The eight types

```
PERSISTED (written to SQLite):
  Event           ← the only thing actually stored

PROJECTIONS (SQL views over events):
  Task            ← current state of a task
  Session         ← latest Claude session per (task, role)
  StageProgress   ← attempts + status per (task, stage)

CONFIG (loaded from .stagent.yaml, never persisted):
  Role            ← who executes (model, container, skill)
  StageDef        ← name, type, hooks, retries, output, role
  Hook            ← interface + concrete validators/actions
  Flow            ← named ordered list of StageDef names
```

### Persisted

```go
type Event struct {
    ID        int64           // autoincrement
    TaskID    int64           // owning task
    Type      EventType       // task.created, stage.entered, stage.completed, ...
    Stage     string          // dot path, e.g. "implement.code" (empty for task-level)
    Role      string          // who emitted it (developer, manager, ...)
    Actor     ActorKind       // agent | human | heartbeat | system
    Payload   json.RawMessage // type-specific data
    CreatedAt time.Time
}

type EventType string

const (
    EventTaskCreated      EventType = "task.created"
    EventTaskAborted      EventType = "task.aborted"

    EventStageEntered     EventType = "stage.entered"     // attempt N started
    EventStageCompleted   EventType = "stage.completed"   // exit hooks passed
    EventStageFailed      EventType = "stage.failed"      // attempts exhausted
    EventStageRedirected  EventType = "stage.redirected"  // hook moved us to a different stage
    EventStageRetrying    EventType = "stage.retrying"

    EventSessionStarted   EventType = "session.started"   // claude -p invoked, session id captured
    EventSessionEnded     EventType = "session.ended"     // process exited, reason recorded
    EventSessionResumed   EventType = "session.resumed"   // claude --resume

    EventHookFired        EventType = "hook.fired"
    EventHumanApproved    EventType = "human.approved"
)
```

There is no `events.update` — the log is append-only. State corrections happen by appending a corrective event, never by editing history.

### Projections

These are **SQL views** (defined in [SCHEMA.md](./SCHEMA.md)), not Go structs you write to. The Go structs below are what `SELECT` returns into:

```go
type Task struct {
    ID             int64
    Title          string
    Flow           string
    CurrentStage   string      // last stage.entered, modulo completion
    Status         TaskStatus  // active | waiting_human | completed | failed | aborted
    WorktreeDir    string
    Branch         string
    CreatedAt      time.Time
    UpdatedAt      time.Time
}

type Session struct {
    TaskID       int64
    Role         string
    ClaudeID     string       // session UUID from claude
    LastUsedAt   time.Time
    LastStage    string       // most recent stage this session worked on
    Ended        bool
    EndReason    EndReason    // completed | exited | killed | unknown
}

type StageProgress struct {
    TaskID         int64
    Stage          string
    Attempts       int
    Status         StageStatus // not_started | in_progress | waiting_human | completed | failed
    LastEventAt    time.Time
}
```

### Config

```go
type Role struct {
    Name      string
    Model     string  // opus | sonnet | haiku
    SkillFile string  // optional path to system prompt
    Dangerous bool    // pass --dangerously-skip-permissions; required true for agent roles in v1
}

type StageType string
const (
    StageAgent     StageType = "agent"      // Claude session
    StageHuman     StageType = "human"      // pause for approval
    StageHeartbeat StageType = "heartbeat"  // daemon-driven
)

type StageDef struct {
    Name     string      // bare identifier: "code", "plan_review"
    Type     StageType
    Role     string      // which Role executes (agent stages only)
    Output   string      // artifact filename: "spec.md"
    Retries  int         // max additional attempts after the first; default 0
    Hooks    StageHooks
    Skill    string      // optional skill file override
}

type StageHooks struct {
    Enter      []Hook   // run on stage.entered; failures rollback
    Exit       []Hook   // run on completion attempt; failures block or retry
    Heartbeat  []Hook   // run every tick while in this stage (heartbeat stages only)
}

type Hook interface {
    Run(ctx *HookCtx) HookResult
    MinInterval() time.Duration   // 0 = every tick; useful for wait_for_ci etc.
}
// concrete: FileExists, SectionCheck, MinWords, RunShell, WaitForCI, ...

type Flow struct {
    Name   string
    Stages []string   // ordered list of StageDef names
}
```

## Task creation

The surface is deliberately tiny:

```
stagent task new "<title>"                   # uses flow=default
stagent task new "<title>" --flow <name>     # opt into a non-default flow
```

Title is the only required input. Flow is the only knob. No `--priority`, `--labels`, `--from-file`, etc. — these are YAGNI for v1. If the user wants to seed the first artifact with prose, they edit it in the worktree before the heartbeat first ticks. If they want context the agent should read, they put it in the role's skill file.

`task new` does three things:

1. Allocates the next sequential task ID.
2. Creates a git worktree at `.worktrees/task-<id>/` on a new branch `task-<id>`.
3. Appends a `task.created` event:
   ```json
   { "title": "Fix login bug", "flow": "default",
     "worktree_dir": "/abs/path/.worktrees/task-001", "branch": "task-001" }
   ```

The heartbeat picks it up on the next tick and enters the first stage of the chosen flow.

## Lifecycle of a task

```
stagent task new "..." ──▶ Event: task.created
                              │
                              ▼
heartbeat tick ──▶ resolves first stage in flow
                              │
                              ▼
                  Event: stage.entered (attempt=1)
                              │
                              ▼
                  StageDef.Type == "agent"?
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
         agent             human            heartbeat
            │                 │                 │
   start/resume claude    wait for         run heartbeat
   session                stagent approve  hooks each tick
            │                 │                 │
   process exits         user runs        until exit hooks
   (any reason)          stagent approve  pass
            │                 │                 │
            └─────────┬───────┘                 │
                      ▼                         │
            heartbeat runs                      │
            exit hooks                          │
                      │                         │
            ┌─────────┴─────────┐               │
            pass                fail            │
            │                   │               │
            ▼                   ▼               │
            Event:        attempts < retries?   │
            stage.        ┌──────┴──────┐       │
            completed     yes           no      │
                          │             │       │
                          ▼             ▼       │
                    Event:         Event:       │
                    stage.         stage.failed │
                    retrying       (escalate)   │
                          │                     │
                          ▼                     │
                    stage.entered (attempt=N+1) │
                    resume agent with           │
                    hook errors in prompt       │
                                                │
                              ┌─────────────────┘
                              ▼
                  next stage in flow
                  (or task.completed if last)
```

Every transition is driven by the heartbeat reading the event log + checking artifacts on disk. Nothing else writes to the log.

## Stage types in detail

### `agent` stages

- Heartbeat sees the stage is current and no session is active for `(task, role)`.
- Heartbeat invokes `claude -p "<initial prompt>" --dangerously-skip-permissions` (governed by `Role.Dangerous`), captures the session ID, emits `session.started`.
- The prompt instructs the agent what to produce (artifact name, sections to fill, checkboxes to complete).
- While the process is running, the heartbeat does nothing — just waits.
- When the process exits (clean finish, OOM, killed, token limit — reason doesn't matter), the heartbeat runs exit hooks:
  - Hooks pass → `stage.completed`
  - Hooks fail + attempts left → `stage.retrying` → re-enter with `--resume <id>`, hook errors prepended to the resume prompt
  - Hooks fail + attempts exhausted → `stage.failed`

The agent never decides when it's "done" — it just exits when it thinks so. The hooks (which include section-completion checkbox checks via `section_check`) are the authoritative judgment.

### `human` stages

- Heartbeat enters the stage. No session started.
- Status becomes `waiting_human`.
- User runs `stagent approve <task>` (or any command bound to `human.approved`).
- Heartbeat sees the approval event, runs exit hooks, completes the stage.

### `heartbeat` stages

- Heartbeat enters the stage. No Claude session.
- On every tick while in this stage, runs `StageHooks.Heartbeat` hooks.
  Examples: `wait_for_ci`, `git_push`, `ensure_pr_exists`, `cleanup_containers`.
- When all heartbeat hooks return "done", exit hooks run and stage completes.

## Sessions

A `Session` is a Claude session ID, scoped to a `(task, role)` pair. The same session continues across stages for that role — e.g. the `developer` role's session spans `implement.code`, `implement.address_review`, and any retries.

This is a deliberate choice. Continuity across stages preserves context. Per-stage isolation would lose it.

### How session IDs are captured

Claude Code writes session transcripts to `~/.claude/projects/<cwd-encoded>/<session-uuid>.jsonl`. When we invoke `claude -p` we capture the session ID by either:

1. **Preferred** — passing `--session-id <uuid>` if Claude Code supports specifying it (we generate the UUID ourselves and store it before invoking). *This needs verification — see [open questions](#open-questions).*
2. **Fallback** — invoking `claude -p`, then reading the most-recently-modified JSONL in the project directory and parsing its filename for the UUID.

Once captured, we emit `session.started` with the UUID in the payload. Subsequent invocations: `claude -p "<msg>" --resume <uuid>`.

### Why not name sessions?

Claude Code doesn't natively support named sessions as of writing. The UUID-in-DB approach is equivalent and gives us one stable handle per (task, role).

## Retries

Each `StageDef` has a `retries` field, default 0 (meaning 1 attempt total). On stage failure:

```
attempt_count = COUNT(events WHERE type='stage.entered' AND task=X AND stage=Y)
if attempt_count <= retries:   # retries=0 → 1 attempt allowed
    emit stage.retrying
    emit stage.entered (attempt = attempt_count + 1)
    resume the session if one exists
else:
    emit stage.failed
    # task transitions to status=failed, surfaces in UI for human intervention
```

Retries reuse the Claude session (same UUID, `--resume`). The agent sees its prior context plus the new attempt's prompt, which includes whatever the exit hook complained about.

**When attempts are exhausted**, `stage.failed` is emitted and the task's status becomes `failed` (surfaces in the viewer). No notifications, no Slack — escalation is whatever the user wires up via a `run_shell` hook on `stage.failed`. Keeps the core small.

## Rollback

`stagent rewind <task>` emits a corrective event that voids the most recent `stage.completed` for a task and re-enters the previous stage. Implemented as a new `stage.rewound` event type; the `tasks` view treats it as a roll-back of the latest completion. No data is deleted — the original events stay; the view just stops considering them once a `stage.rewound` references them.

Use cases: a human-approved stage was approved by mistake; an agent's exit hooks let something through that shouldn't have passed.

## Concurrency

The heartbeat is one process, ticking every `heartbeat.interval`. Within a tick:

- **Tasks run in parallel** (one goroutine per active task). Tasks are independent — different worktrees, different sessions, different stages.
- **Within a task, stages are serial**. The state machine doesn't have a notion of "two stages of the same task at once."
- **Hook execution is serial within a stage**. Enter and exit hooks run in declared order; the first failure short-circuits.

SQLite handles the concurrent appends without contention (see SCHEMA.md). The daemon never holds a long-running transaction.

## How completion works

The signal that an agent stage is ready for judgment is **process exit**. Any reason — clean finish, token limit, OOM, killed — triggers the same evaluation path. The heartbeat runs the stage's exit hooks (deterministic Go) and decides:

- Hooks pass → `stage.completed`
- Hooks fail + retries available → `stage.retrying`, resume the session with hook errors prepended to the next prompt
- Hooks fail + no retries → `stage.failed`

**Agents do not run hooks. Agents do not signal completion explicitly.** They work, then exit. The system judges.

Implications:

- If the agent thought it was done but missed something (tests fail, a checkbox in the artifact is unchecked, the output file is empty), the exit hook catches it. The agent resumes with structured feedback and tries again.
- If the agent crashed mid-work, same path runs: hooks fail, retry. Recovery code is the same code as the normal "you missed a step" path.
- The state machine is fully recoverable across daemon restarts — the daemon only needs to read events + check process state.
- We never parse Claude's stop reasons, token-exhaustion messages, or exit codes. They're noise.

The exit hooks themselves are how you encode "is this done?" — typically `section_check: { file: plan.md, section: Completion, expect: all_checked }` catches a half-finished artifact with unchecked items.

## Commands

Commands are the user-facing surface — like [`just`](https://github.com/casey/just) recipes, but they emit events into the log.

There are two kinds:

### Built-in commands (Go)

```bash
stagent init
stagent task new "<title>"
stagent task list
stagent task show <id>
stagent approve <id>             # emits human.approved
stagent restart <id>              # kills session, emits stage.retrying
stagent abort <id>                # emits task.aborted
stagent run                       # runs the heartbeat daemon
stagent status                    # current state of all tasks (queries views)
stagent log <id>                  # event log for a task (tails)
stagent session <id> <role>       # prints the claude session id, for terminal resume
```

Each is a thin wrapper that emits one or more events.

### User recipes (YAML)

`.stagent.yaml` can declare additional recipes, intended to stay as concise as `just`:

```yaml
commands:
  ship:
    desc: Approve current stage and push
    run: |
      stagent approve {{task}}
      git push

  open:
    desc: Open the current task's worktree in iTerm
    run: open -a iTerm {{task.worktree_dir}}
```

Invoked as `stagent ship 42`. No magic — just shell-out with templating from the task projection. If a recipe needs to be more than ~3 lines, it should probably be a Go command instead.

## SwiftUI integration

The Mac viewer is a separate, thin app:

- **Reads** SQLite directly (GRDB), uses the `tasks` and `sessions` views.
- **Watches** the SQLite WAL file (`.stagent/stagent.db-wal`) via FSEvents for push refresh. In WAL mode the `-wal` file is touched on every commit. The viewer's reaction is to advance its "last seen event id" cursor and query `SELECT * FROM events WHERE id > :cursor` to see exactly what changed.
- **Writes** by shelling out to the `stagent` CLI (`Process` API).
- **Opens terminals** by shelling out to `osascript` against iTerm — e.g. to resume a Claude session in a real Claude Code terminal: `osascript -e 'tell application "iTerm" to ... claude --resume <uuid>'`.

The daemon doesn't know the viewer exists. No IPC, no API, no sentinel file. The SQLite file is the contract.

**Liveness:** the daemon writes a PID file at `.stagent/daemon.pid` on start and removes it on graceful exit. `stagent status` checks `kill -0 $(cat .stagent/daemon.pid)` to know if the daemon is alive. Cheaper and more reliable than emitting periodic events.

## Testing strategy

The state machine is the system. Most of the test surface is:

1. **Event-log property tests.** Given a sequence of events, the projections must satisfy invariants:
   - A task is in exactly one stage at a time
   - `attempts > 0` after `stage.entered`
   - `session_started` for a (task, role) precedes any `session_resumed` for the same pair
   - `task.completed` requires the last stage in the flow to have `stage.completed`
2. **Hook contract tests.** Each Hook implementation, given inputs, produces deterministic results.
3. **Heartbeat fixture tests.** Run the heartbeat against a frozen event log + filesystem snapshot, assert exactly which new events get emitted.
4. **End-to-end with a mock `claude` binary.** A fake `claude` that reads scripted responses from a file, used to drive whole flows without touching the real API.

The goal: every path through the state machine has a test that pins it. Adding a new stage type or event type without a test should fail CI.

## Decisions (locked in)

- **Daemon scope:** per-repo. `stagent run` in each project's directory. No global daemon, no project registry, no IPC. The Mac viewer talks to one project at a time (open from a project's worktree path).
- **Containers:** none in v1. Agents run on the host inside the task's git worktree with `--dangerously-skip-permissions`. The worktree provides enough isolation that a misbehaving agent doesn't corrupt the user's main checkout. **Future:** a single shared container that holds all stagent activity, scoped to "protect the user's machine," not "protect tasks from each other."
- **GitHub integration:** none in v1. `stagent` is purely local. Users wire `gh` calls via `run_shell` hooks or `commands:` recipes if they want PR/issue lifecycle.
- **Task creation:** title + optional `--flow`. Nothing else.
- **Worktrees:** always. `.worktrees/task-<id>/` on branch `task-<id>`. No in-place mode.
- **Concurrency:** parallel per task, serial within a task.
- **Rollback:** `stagent rewind <task>` via a `stage.rewound` corrective event.
- **Failure escalation:** status change only. Notifications are a user-wired hook.
- **Skill files:** `.stagent/skills/<name>.md`, checked into git. Stage `Skill` field is optional; falls back to role's skill, then to a built-in default.

## Verification spikes (not blocking design, but needed before code)

1. **`claude -p` and `--session-id`** — does Claude Code's CLI accept a caller-supplied UUID to *create* a session with? If yes, we generate the UUID, store it, then invoke. If no, we invoke first and read the newest JSONL in `~/.claude/projects/<cwd-encoded>/` to capture the auto-generated UUID. Either works; we just need to know which path the v1 code takes.
2. **`claude --resume <uuid> -p "msg"`** — confirm resume works in headless (`-p`) mode and that subsequent turns extend the same JSONL. Should — but worth a 5-minute test before relying on it.
