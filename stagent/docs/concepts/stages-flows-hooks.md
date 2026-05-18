# Stages, flows, hooks

This is the core of stagent. Everything else (the event log, the CLI, the SwiftUI viewer) is plumbing around the state machine described here.

## Flow

A flow is just an ordered list of stage names declared in `.stagent.yaml`:

```yaml
flows:
  default:
    - setup
    - code
    - pr
    - review
    - human_review
    - cleanup

  quick:
    - setup
    - code
    - cleanup
```

A task picks a flow at creation time (`stagent new "<title>" --flow quick`) and walks through it. The flow never branches in YAML — branching happens at runtime via hook **redirects** (covered below).

## Stage

A stage has a name, a type, and a set of hooks. Stages also have a `max_runs` budget — the total number of times the stage can be entered across the task's lifetime, counting all reasons (initial flow, retries, redirects, manual `stagent goto`).

```yaml
stages:
  code:
    type: agent
    role: developer
    max_runs: 7              # generous: review and CI can redirect back
    hooks:
      enter:
        - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && git rebase origin/main", fail_on_nonzero: true }
      exit:
        - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && go test ./...", fail_on_nonzero: true }
        - section_check: { section: "Implementation plan", expect: all_checked }
```

### Stage types

| Type | What happens during the stage | When it completes |
|---|---|---|
| `agent` | A Claude session runs as a child of the runner. The runner watches the process; while it's alive, no hooks fire (except `enter` at entry). | Process exits → exit hooks run → stage completes or retries or redirects. |
| `human` | No process runs. The runner ticks tick hooks (if any) and waits. | Either `stagent approve <task>` is called, OR all tick hooks return `Pass` on the same tick. |
| `script` | No process runs. The runner ticks tick hooks on every heartbeat (subject to each hook's `min_interval`). | All tick hooks return `Pass` on the same tick → exit hooks run → stage completes. |

### Agent stages

The most common type. An `agent` stage:

1. Resolves the Claude session for `(task, role)`. If none exists (first time this role works on this task), generates a UUID and emits `session.started`. If one exists, uses `--resume <uuid>`.
2. Invokes `claude -p "<stage prompt + redirect message if any>" --session-id <uuid> --system-prompt "$(cat prompts/roles/<role>.md)" --dangerously-skip-permissions`. The system prompt is only set on the FIRST invocation for the session.
3. Waits for the child to exit. Process exit — for any reason: clean finish, OOM, killed, token limit — triggers the same evaluation path.
4. Runs `exit` hooks. Their collective verdict determines what happens next:
   - All `Pass` → `stage.completed`.
   - Any `Fail` + retry budget left → resume the session with hook errors prepended, retry.
   - Any `Fail` + budget exhausted → `stage.failed`.
   - Any `Redirect(target, message)` → emit `stage.completed` (the work was done — a verdict was reached) then `stage.entered(target, reason: redirect)`.

Agents never run hooks themselves. They never decide when they're done. They work, they exit, the runner judges.

### Human stages

Two parallel completion paths — whichever fires first wins:

1. **Explicit:** `stagent approve <task>` emits `human.approved`, the runner runs exit hooks, stage completes.
2. **Detected:** all tick hooks return `Pass` on the same tick — e.g. `wait_for_merge` polls the PR and returns `Pass` once it's merged in GitHub. Exit hooks then run.

Tick hooks on human stages can also redirect mid-wait: e.g. a `ci_status` hook polling every 5 minutes returns `Pass` while CI is green and `Redirect(code, <ci logs>)` if it goes red during the human's review.

### Script stages

Fully automated. No Claude, no human input. On every heartbeat tick (subject to each hook's `min_interval`), the runner runs tick hooks. When they all return `Pass` together, exit hooks run.

Common uses: setup (worktree creation), pr (push + CI wait), cleanup (teardown).

A script stage's hooks can redirect just like an agent stage's: a `ci_status` hook in the `pr` stage detects test failures and returns `Redirect(code, <ci logs>)` — the developer's session resumes with the CI output.

## Hooks

A hook is a Go function:

```go
type Hook interface {
    Run(ctx *HookCtx) HookResult
    MinInterval() time.Duration   // 0 = every tick; ignored for enter/exit
}

type HookResult struct {
    Verdict Verdict        // Pass | NotYet | Fail | Redirect
    Target  string         // stage name; only when Redirect
    Message string         // prepended to next agent prompt on Fail/Redirect
}
```

Hooks attach to stages at one of three slots:

| Slot | When it runs | Stage types | Notes |
|---|---|---|---|
| `enter` | Once, when the stage is entered (any reason) | all | Failure aborts entry; useful for setup actions like worktree creation. |
| `exit` | When the stage attempts to complete | all | Determines whether the stage actually completes or retries/redirects. |
| `tick` | Every heartbeat while in the stage | `script`, `human` only | Subject to `min_interval`. NOT supported on `agent` stages — agents own their own turn. |

### Verdicts

| Verdict | Meaning |
|---|---|
| `Pass` | This hook is satisfied. If all other hooks at this slot also `Pass`, the stage proceeds. |
| `NotYet` | Valid only for `tick` hooks. Keep waiting; check again next tick. |
| `Fail` | Trigger retry-or-fail. Hook's `Message` becomes the developer's next prompt. |
| `Redirect(target, message)` | Route to `target` stage with `message`. Loop-backs (review → code) are redirects. |

Pass / Fail / Redirect are the three terminal verdicts. NotYet is a "not yet — try again" only for tick hooks.

### `max_runs` — one budget for all entries

Each stage has a `max_runs` field: the total number of times the stage can be entered across the task. **All reasons count against it**: initial flow, retries, redirects from downstream, manual `stagent goto`. One budget, no special cases.

```
attempts = COUNT(events WHERE type='stage.entered' AND task=X AND stage=Y)

on any attempt to enter the stage:
    if attempts >= stage.max_runs:
        emit stage.failed
    else:
        emit stage.entered
```

Defaults if not specified:

| Stage type | Default `max_runs` |
|---|---|
| `agent` | 3 |
| `script` | 3 |
| `human` | 1 |

`code` typically wants more (5–7) to absorb review-loop iterations. `review` typically wants 3 to cap how many times a reviewer can reject before the task escalates to a human.

## Redirects

Loop-backs are not a special concept. They're a hook verdict.

```yaml
review:
  type: agent
  role: reviewer
  hooks:
    exit:
      - section_check:
          section: "Reviews > /^Pass \\d+$/[-1]"
          expect: all_checked
          on_fail:
            redirect_to: code
            message_from_section: "Reviews > /^Pass \\d+$/[-1]"
```

When the reviewer exits with at least one unticked box in the latest `### Pass N` subsection, `section_check` returns `Redirect(code, <text of Pass section>)`. The runner:

1. Appends `stage.completed` for `review` (the work was done — a verdict was reached, even if "changes requested").
2. Appends `stage.entered(code, reason: redirect, from_stage: review)`.
3. Resumes the developer's session (`claude --resume <uuid>`) with the reviewer's notes prepended to the prompt.

The developer's `max_runs` budget continues counting. Each round of `code → review → code → review → …` adds one to each stage's count. When `review.max_runs` is exhausted, the task fails for human attention.

See [the review loop pattern](../patterns/review-loop.md) for a full worked example.

### `stagent goto` — the human escape hatch

```bash
stagent goto <task> <stage> -m "your message here"
```

Emits `stage.entered` with `reason: human_goto`. Same machinery as a hook redirect, just initiated by a human instead of a hook. There is no separate "rewind" concept — `goto` is the one human-issued routing primitive.

## Lifecycle of a task

```
stagent new "..." ──▶ Event: task.created
                              │
                              ▼
heartbeat tick ──▶ resolves first stage in flow
                              │
                              ▼
                  Event: stage.entered (attempt=1, reason=flow)
                              │
                              ▼
                  StageDef.Type == ?
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
         agent             human             script
            │                 │                 │
   start/resume claude    wait for         run tick hooks
   session                stagent approve  each heartbeat tick
            │                 │                 │
   process exits         user runs        until tick hooks
   (any reason)          stagent approve  all return Pass
            │                 │                 │
            └─────────┬───────┘                 │
                      ▼                         │
            runner runs exit hooks              │
                      │                         │
            ┌─────────┼──────────────┐          │
            pass      redirect       fail       │
            │         │              │          │
            ▼         ▼              ▼          │
        Event:    Event:        attempts        │
        stage.    stage.        < max_runs?     │
        completed completed     ┌────┴────┐     │
                  Event:        yes       no    │
                  stage.        │         │     │
                  entered       ▼         ▼     │
                  (target,    Event:   Event:   │
                  reason=     stage.   stage.   │
                  redirect)   entered  failed   │
                              (reason= (task    │
                              retry)   surfaces │
                              resume   for      │
                              w/ hook  human)   │
                              errors            │
                                                │
                              ┌─────────────────┘
                              ▼
                  next stage in flow
                  (or task.completed if last)
```

Every transition is driven by the runner reading the event log and watching child processes. Nothing else writes to the log.
