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

    EventStageEntered     EventType = "stage.entered"     // payload carries reason: flow|retry|redirect|human_goto
    EventStageCompleted   EventType = "stage.completed"   // exit hooks passed (or redirected — work was done)
    EventStageFailed      EventType = "stage.failed"      // attempts exhausted

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
    StageAgent  StageType = "agent"   // Claude session does the work
    StageHuman  StageType = "human"   // paused for human review
    StageScript StageType = "script"  // daemon executes hooks deterministically
)

type StageDef struct {
    Name     string      // bare identifier: "code", "plan_review"
    Type     StageType
    Role     string      // which Role executes (agent stages only)
    Output   string      // artifact filename: "spec.md"
    MaxRuns  int         // total entries to this stage allowed across a task
    Hooks    StageHooks
    Skill    string      // optional skill file override
}

type StageHooks struct {
    Enter []Hook   // run on stage.entered; failures rollback
    Exit  []Hook   // run when the stage attempts to complete (agent exit, human approve, script tick says "done")
    Tick  []Hook   // run every daemon tick while in this stage (script stages only)
}

type Hook interface {
    Run(ctx *HookCtx) HookResult
    MinInterval() time.Duration   // 0 = every tick; useful for wait_for_ci etc.
}

type HookResult struct {
    Verdict Verdict   // Pass | Fail | Redirect
    Target  string    // stage name; only set when Verdict == Redirect
    Message string    // human-readable; prepended to agent's next prompt on Fail/Redirect
}

type Verdict int
const (
    Pass Verdict = iota
    Fail
    Redirect
)
// concrete: FileExists, SectionCheck, MinWords, RunShell, WaitForCI, SectionRedirect, ...

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
                  StageDef.Type == ?
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
         agent             human             script
            │                 │                 │
   start/resume claude    wait for         run tick hooks
   session                stagent approve  each daemon tick
            │                 │                 │
   process exits         user runs        until tick hooks
   (any reason)          stagent approve  report done
            │                 │                 │
            └─────────┬───────┘                 │
                      ▼                         │
            heartbeat runs                      │
            exit hooks                          │
                      │                         │
            ┌─────────┼──────────────┐          │
            pass      redirect       fail       │
            │         │              │          │
            ▼         ▼              ▼          │
        Event:    Event:        attempts        │
        stage.    stage.        < retries?      │
        completed completed     ┌────┴────┐     │
                  Event:        yes       no    │
                  stage.        │         │     │
                  entered       ▼         ▼     │
                  (target,    Event:   Event:   │
                  reason=     stage.   stage.   │
                  redirect)   entered  failed   │
                              (reason= (escalate)
                              retry)            │
                              resume            │
                              with hook         │
                              errors            │
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
- Heartbeat generates a UUID, emits `session.started` with it, then invokes `claude -p "<initial prompt>" --session-id <uuid> --dangerously-skip-permissions` (last flag governed by `Role.Dangerous`).
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

### `script` stages

- Heartbeat enters the stage. No Claude session, no human involvement.
- On every tick while in this stage, runs `StageHooks.Tick` hooks (subject to each hook's `MinInterval`).
  Examples: `wait_for_ci`, `ensure_pr_exists`, `cleanup_containers`.
- When all tick hooks return "done", exit hooks run and the stage completes (or redirects).
- **Escalation works through redirects.** A script stage's hook can return `Redirect(stage, message)` exactly like an agent stage's hook. Example: a `ci` stage detects test failures and returns `Redirect(code, <ci logs>)` — the developer's session resumes with the CI output in its prompt. No new escalation concept needed.

## Sessions

A `Session` is a Claude session ID, scoped to a `(task, role)` pair. The same session continues across stages for that role — e.g. the `developer` role's session spans `implement.code`, `implement.address_review`, and any retries.

This is a deliberate choice. Continuity across stages preserves context. Per-stage isolation would lose it.

### How session IDs are captured

We generate the UUID ourselves and pass `--session-id <uuid>` on first invocation. Claude Code writes the session transcript to `~/.claude/projects/<cwd-encoded>/<that-uuid>.jsonl` (the encoded-cwd substitutes `-` for `/`, e.g. `/Users/dave/proj` → `-Users-dave-proj`). Verified against `claude` 2.1.143.

The flow:

1. `uuid := uuid.NewV4()`
2. Emit `session.started` event with the UUID.
3. Invoke `claude -p "<prompt>" --session-id <uuid> --dangerously-skip-permissions`.
4. Subsequent invocations for the same `(task, role)`: `claude -p "<msg>" --resume <uuid> --dangerously-skip-permissions`.

We never need to scan the project directory to discover IDs. The DB is the authoritative source.

Named sessions don't exist in Claude Code; UUIDs are required. Our event log gives us the per-`(task, role)` indirection we want.

## Run budgets (`max_runs`)

Each `StageDef` has a `max_runs` field: the total number of times the stage may be entered across the task's lifetime, counted across *every reason* — initial, retry, redirect, human_goto. One budget, no special cases.

```
attempts = COUNT(events WHERE type='stage.entered' AND task=X AND stage=Y)
on any attempt to enter the stage (flow / retry / redirect / human_goto):
    if attempts >= stage.max_runs:
        emit stage.failed
    else:
        emit stage.entered (attempt: attempts+1, reason: <how>)
```

This collapses "retry budget" and "loop budget" into one number. `code` with `max_runs: 7` allows many review-loop iterations. `review` with `max_runs: 3` caps how many times a reviewer can reject before the task escalates.

**Defaults:**

| Stage type | default `max_runs` |
|---|---|
| `agent` | 3 (one initial + room for two retries/loops) |
| `script` | 3 (transient failures are common; retries cheap) |
| `human` | 1 (humans don't typically retry; override for re-approval loops) |

**When the budget is exhausted**, `stage.failed` is emitted and the task's status becomes `failed`. The task surfaces in the viewer for a human to handle — `goto` somewhere, edit the artifact, or abort. No notifications in v1; users can wire `run_shell` on a future `stage.failed` post-completion hook for Slack/email.

Retries and redirects both reuse the Claude session for the target stage (same UUID, `--resume`). The agent sees its prior context plus a prompt prefix containing the hook's `Message` — typically what failed and how to fix it.

**Future direction (not v1):** an *observer* agent role inspects failed stages and either applies a fix (returning to `in_progress`) or routes to human review with a structured explanation. This sits between "budget exhausted" and "human takes over." For v1, we skip the observer and escalate directly to humans.

## Redirects (loop-backs)

Going back to an earlier stage is **not** an undo. It's a normal hook outcome.

A hook returns one of three verdicts:

- **Pass** → flow proceeds to next stage in order
- **Fail** → retry (if attempts remain) or `stage.failed`
- **Redirect(stage)** → emit `stage.completed` on the current stage (the work was done), then `stage.entered(stage, reason: "redirect")` on the target

A redirect pointing forward is rare; a redirect pointing backward is the **review loop**, the most common non-linear flow. Same machinery either way.

### Review-loop example

```yaml
code_review:
  type: agent
  role: reviewer
  output: review.md
  hooks:
    exit:
      - file_exists: { path: review.md }
      - section_check: { file: review.md, section: Verdict, expect: all_checked }
      - section_redirect:
          file: review.md
          when_checked: "Request changes"
          redirect_to: code
```

The reviewer fills in `review.md`, checking exactly one of two sections: "Approve" or "Request changes." On exit, hooks run. The `section_redirect` hook reads the file: if "Request changes" is checked, it returns `Redirect(code)`. Otherwise it passes and the flow continues to the next stage.

When the redirect fires:

1. `stage.completed` for `code_review` (the work was done — reviewer reached a verdict).
2. `stage.entered` for `code` with `reason: "redirect"`, `from_stage: "code_review"`.
3. The `code` agent's session is resumed (`--resume <uuid>`) with the reviewer's message prepended to the prompt.
4. The code stage's retry budget resets — each redirect cycle is its own attempt sequence.

`code → code_review → code → code_review → ...` loops naturally until the reviewer approves or the user intervenes.

### `stage.entered` reasons

| `reason` | When |
|---|---|
| `flow` | Normal forward transition from the previous stage |
| `retry` | Same stage's exit hooks failed; trying again within the same cycle |
| `redirect` | Downstream stage redirected back here |
| `human_goto` | User ran `stagent goto <task> <stage>` |

### `stagent goto` — the human escape hatch

When a human needs to send a task to a specific stage manually:

```
stagent goto <task> <stage>
```

Emits `stage.entered` with `reason: "human_goto"`. Same machinery as hook redirects. There is no `rewind` command and no `stage.rewound` event — `goto` is the one human-issued routing primitive.

Hooks are pre-completion gates. Redirects are a hook verdict that happens to route to a chosen target. `goto` is a human exercising the same routing primitive. The three vocabularies collapse into one.

## Artifacts and templates

Stage outputs are markdown files. They need templates so agents have a structure to fill into — section headings, checkboxes, prompts. Without templates, every agent invents its own layout and the hooks that look for specific sections break.

**Layout:**

```
.stagent/
  templates/
    spec.md          ← committed to git, project config
    plan.md
    review.md
  tasks/
    001/             ← gitignored, one dir per task
      spec.md        ← copied from template on stage.entered
      plan.md        ← edited by the agent
      review.md
```

- **Templates** live at `.stagent/templates/<output>` and are checked into git alongside skills. They define the structure the agent fills.
- **Task artifacts** live at `.stagent/tasks/<id>/<output>` in the **main repo** (not the worktree). They are gitignored.

**Lifecycle:**

1. On `stage.entered`, the heartbeat invokes the stage's enter hooks. For agent stages, this typically includes `create_from_template: { template: <output>, dest: <output> }` which copies `.stagent/templates/<output>` to `.stagent/tasks/<id>/<output>` if the file doesn't already exist.
2. The agent's prompt includes the **absolute path** to the artifact. The agent's CWD is the worktree (for code edits via Read/Edit/Write tools on project files), but it reads and writes its artifact at the absolute path it was given.
3. The agent's exit hooks check the artifact (`file_exists`, `section_check`, `min_words`).
4. After `stage.completed`, the artifact stays. It is never deleted automatically.
5. Subsequent stages can read prior stages' artifacts — e.g. the `code` stage reads the `plan.md` produced by `plan`. Same absolute path, same file.

**Why not in the worktree, why not committed?**

- *Not in the worktree:* the worktree is for code. Mixing workflow files into it conflates two concerns. Also the daemon (running in the main repo) would have to chase artifacts across N worktrees.
- *Not committed:* would pollute the project's git history with workflow output. Agenttree got this right with a separate `_agenttree/` repo; stagent keeps it gitignored.

**Archival:** artifacts accumulate forever by default — markdown is tiny. If cleanup ever matters, `stagent task archive <id>` (deferred) can tar them up.

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
stagent approve <id>              # emits human.approved (completes a human stage)
stagent goto <id> <stage> [-m "msg"]   # emits stage.entered with reason=human_goto; -m prepends a message to the resumed agent's prompt
stagent restart <id>              # kills the session, re-enters current stage as a retry
stagent abort <id>                # emits task.aborted
stagent run                       # runs the heartbeat daemon (per-repo, foreground)
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
- **Stage types:** `agent`, `human`, `script` (not "heartbeat" — that's the daemon's name, not a stage type). Tick hooks on script stages live at `hooks.tick`.
- **Routing primitives:** Hook returns `Pass | Fail | Redirect(stage, message)`. Loop-backs (review→code) are redirects to earlier stages. `stagent goto <task> <stage> [-m]` is the human-issued redirect. No `rewind`, no `stage.rewound`.
- **Run budget:** `max_runs` per stage, counting all entries (initial + retry + redirect + human_goto). Defaults: 3 for agent/script, 1 for human.
- **Failure escalation:** status change only. Notifications are a user-wired hook.
- **Skill files:** `.stagent/skills/<name>.md`, checked into git. Stage `Skill` field is optional; falls back to role's skill, then to a built-in default.
- **Default flow** (what `stagent init` scaffolds): `define → plan → plan_review → code → review → ci → human_review`. Loops happen via `review`/`ci` redirecting to `code`.

## Verification (resolved)

Verified against `claude` 2.1.143:

- `claude -p --session-id <uuid> "<prompt>"` accepts a caller-supplied UUID and writes the transcript to `~/.claude/projects/<encoded-cwd>/<that-uuid>.jsonl`. We generate UUIDs ourselves; no post-invocation directory scan needed.
- `claude --resume <uuid> -p "<msg>"` works in headless mode and appends to the same JSONL.
- Encoded-cwd substitutes `-` for `/` (e.g. `/Users/dave/proj` → `-Users-dave-proj`, with a leading dash from the leading slash).
- `--dangerously-skip-permissions` is refused when running as root — relevant if we ever add containers.
- `--no-session-persistence` exists if we want one-shot agents that don't write JSONL.
