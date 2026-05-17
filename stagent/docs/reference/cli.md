# CLI reference

Every command stagent ships. Run `stagent --help` for the most current list.

## Project setup

### `stagent init`

Scaffold a new project. Run from the repo root.

```bash
stagent init
```

Creates:

```
.stagent.yaml
.stagent/prompts/roles/{developer,reviewer}.md
.stagent/prompts/stages/{code,review}.md
.stagent/templates/task.md
tasks/                                   # empty directory
```

Appends to `.gitignore`:

```
.stagent/stagent.db*
.stagent/runner.pid
.worktrees/
```

Idempotent. Re-running won't overwrite existing files; it adds anything missing and warns about conflicts.

## Tasks

### `stagent new <title-or-path>`

Register a task. Two forms:

```bash
stagent new "Fix login redirect bug"          # create from template
stagent new tasks/fix-login.md                # register existing file
stagent new "Trivial fix" --flow quick        # opt into a non-default flow
```

Allocates the next task ID, places (or renames) the file at `tasks/<id>-<slug>.md`, and appends a `task.created` event. **Does no filesystem work beyond moving the spec file** — the worktree is created by the `setup` stage on the next heartbeat tick. This means worktree-creation failures (disk full, branch collision) surface as normal `stage.failed` events, retryable via `stagent goto`.

### `stagent list`

Show all tasks with their current stage and status.

```bash
stagent list
```

Example output:

```
 ID  TITLE                            FLOW     STAGE          STATUS         UPDATED
 1   Fix login redirect bug           default  code           active         2m ago
 2   Add user export                  default  human_review   waiting_human  1h ago
 3   Typo in login form               quick    cleanup        active         12s ago
 4   Migration to new auth provider   default  review         failed         3d ago
```

### `stagent show <task-id>`

Detailed view of one task — current stage, attempts on each stage, sessions, last events.

```bash
stagent show 1
```

### `stagent status`

Short status — same data as `list` plus a line about runner liveness:

```
runner: alive (pid 12345, started 2h ago)
 ID  TITLE                            STAGE          STATUS
 1   Fix login redirect bug           code           active
 2   Add user export                  human_review   waiting_human
```

### `stagent log <task-id>`

Tail the event log for a task. Streams new events as they're appended.

```bash
stagent log 1
```

Add `--from <event-id>` to start from a specific point, or `--no-follow` for a one-shot dump.

## Runtime

### `stagent run`

Start the runner. Per-repo. Foreground in v1 — blocks the terminal until `Ctrl-C`.

```bash
stagent run
```

On start, the runner:

1. Acquires `.stagent/runner.pid` (refuses if another runner is alive).
2. Opens `.stagent/stagent.db`, applies schema, recreates views.
3. Loads `.stagent.yaml`.
4. Replays the event log to identify orphan sessions (from prior crashes) and emits `session.ended` for each.
5. Enters the heartbeat loop.

`SIGHUP` reloads `.stagent.yaml`. `SIGINT` / `SIGTERM` stops cleanly (emits `session.ended` for any in-flight Claude children before exiting? — actually no, the children keep running and become orphans for the next start to handle; design choice favors fast shutdown).

### `stagent approve <task-id>`

Mark the current human stage as approved. Emits `human.approved` and triggers a force tick — the runner will run exit hooks on its next iteration.

```bash
stagent approve 2
```

If the current stage is not a human stage, the command errors.

### `stagent goto <task-id> <stage> [-m "<message>"]`

Manually route a task to a chosen stage. Emits `stage.entered` with `reason: human_goto`.

```bash
stagent goto 1 code -m "ignore the reviewer; this is fine"
stagent goto 4 setup
```

If `-m` is provided, the message is prepended to the agent's next prompt (same mechanism as a hook redirect). For non-agent target stages, the message is recorded in the event payload but has no other effect.

Subject to `max_runs` — if the target stage's budget is exhausted, the command errors. (Use case for raising the budget mid-task: edit `.stagent.yaml`, `kill -HUP $(cat .stagent/runner.pid)`, then `stagent goto`.)

### `stagent poll [<task-id>]`

Emit a `force_tick` event. On the next heartbeat iteration, tick hooks run **ignoring `min_interval`**.

```bash
stagent poll                # all active tasks
stagent poll 2              # just task 2
```

Useful when you just merged a PR in the GitHub UI and want `wait_for_merge` to detect it immediately, without waiting for its 1-minute `min_interval`. `stagent approve` and `stagent goto` emit `force_tick` automatically.

### `stagent restart <task-id>`

Kill the current Claude session and re-enter the current stage as a retry.

```bash
stagent restart 1
```

Emits `session.ended(reason: "user_killed")` followed by `stage.entered(reason: retry)`. The task's session is reused (`--resume <uuid>`) so the agent sees its prior context. Counts against `max_runs`.

### `stagent abort <task-id>`

Mark a task as aborted. Emits `task.aborted`.

```bash
stagent abort 3
```

Doesn't touch the worktree (by design — you might want to look at the partial work). To clean up:

```bash
stagent goto 3 cleanup
```

Or do it manually.

## Sessions

### `stagent session <task-id> <role>`

Print the Claude session UUID for `(task, role)`. Used for interactive resume from a terminal:

```bash
SID=$(stagent session 1 developer)
cd /abs/.worktrees/task-001
claude --resume "$SID"
```

The default `.stagent.yaml` defines a `resume` command that wraps this.

## User-defined commands

Any commands declared under `commands:` in `.stagent.yaml` become CLI subcommands. They're templated with task context:

```yaml
commands:
  ship:
    desc: Approve current human stage and push
    run: |
      stagent approve {{.Task.ID}}
      git -C {{.Task.WorktreeDir}} push
```

```bash
stagent ship 2
```

Available template variables: `.Task.ID`, `.Task.Title`, `.Task.Branch`, `.Task.WorktreeDir`, `.Task.Flow`, `.Task.CurrentStage`, `.Task.Status`.

See [Configuration → `.stagent.yaml` → `commands`](../configuration/stagent-yaml.md#commands) for the spec.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success. |
| 1 | Generic error (config invalid, task not found, etc.). |
| 2 | Usage error (missing arg, unknown flag). |
| 3 | Runner already running (`stagent run` when another runner holds `runner.pid`). |
| 4 | Operation refused by state (e.g. `approve` on a non-human stage). |

## Global flags

| Flag | Meaning |
|---|---|
| `--config <path>` | Override `.stagent.yaml` location. |
| `--db <path>` | Override `.stagent/stagent.db` location. |
| `--log-level debug\|info\|warn\|error` | Log level (default `info`). |
| `--json` | Emit machine-readable JSON output for `list`, `show`, `status`, `log`. |
| `--no-color` | Disable color output. |
| `--help` | Show help. |
| `--version` | Show version and exit. |
