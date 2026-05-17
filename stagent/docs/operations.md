# Operations

How the runner actually runs — process model, crash recovery, concurrency, viewer integration.

For the rationale, see [`notes/architecture.md`](https://github.com/davefowler/stagent/blob/main/notes/architecture.md).

## The runner

`stagent run` is a long-running foreground process (in v1; daemonization comes later). Per-repo: one runner per project, not one global runner.

On start, it:

1. **Acquires `.stagent/runner.pid`.** If another runner is already alive (PID file present + `kill -0` succeeds), refuses to start (exit code 3). Stale PID files (process gone) are reclaimed.
2. **Opens `.stagent/stagent.db`.** Applies the schema (idempotent — `CREATE TABLE IF NOT EXISTS` and friends). Drops and recreates all views.
3. **Loads `.stagent.yaml`.** Parses, validates, builds in-memory representation.
4. **Replays the event log for orphans.** For any `(task, role)` with `session.started` but no matching `session.ended`, the runner emits `session.ended` with `reason: "runner_restart_orphan"`. This is how crash recovery works (see below).
5. **Enters the heartbeat loop.** Default interval: 2 seconds.

### The heartbeat loop

One goroutine. Pseudocode:

```
loop {
    sleep until next tick OR signal
    on tick: for each active task, ensure a task worker is running
    on SIGHUP: reload config
    on SIGINT/SIGTERM: shutdown
}
```

The heartbeat doesn't do work. It dispatches. Actual stage execution happens in **task worker** goroutines.

## Task workers

When the heartbeat sees a task without an active worker, it spawns one. The worker owns the per-task state machine:

```
task worker {
    for each stage entry {
        run enter hooks
        if stage type == agent:
            spawn claude -p as child
            wait for child to exit
        if stage type == human:
            wait for `human.approved` event OR all tick hooks pass
        if stage type == script:
            tick until all tick hooks pass

        run exit hooks
        emit stage.completed | stage.failed | stage.entered(redirect)
    }
}
```

Workers are independent — different worktrees, different sessions, different stages. They communicate with the heartbeat only via the event log.

### One process, many workers

There is one OS process (the runner) and N goroutines (the heartbeat + one task worker per active task). This matters because:

- **Single SQLite writer.** All event appends go through one process, serializing trivially.
- **Single PID file.** Liveness is one `kill -0`.
- **The Mac viewer connects to one runner.** Not N runners.
- **Cheap.** Goroutines are bytes, not megabytes. Hundreds of active tasks is fine.

## Process model

Agent stages run `claude -p` as a **direct child** of the runner. The task worker calls `cmd.Start()` then `cmd.Wait()` in a sub-goroutine. When the child exits — for any reason — Wait returns and the worker emits `session.ended` and triggers exit hook evaluation.

**No periodic PID polling.** Event-driven. The OS tells us when the child exited; we react.

The runner never blocks on a single agent. Each task worker manages its own child; the heartbeat keeps ticking; CLI commands are serviced; other workers' completions are processed.

## Concurrency

```
runner process
├── heartbeat goroutine     (1)
├── task worker goroutines  (N — one per active task)
│   └── claude -p child     (when in an agent stage)
└── SQLite connection       (1, shared)
```

- **Tasks run in parallel.** Up to as many active tasks as you have.
- **Within a task, stages are serial.** No "two stages of the same task at once."
- **Hook execution is serial within a slot.** Hooks in `enter`/`exit`/`tick` lists run in declared order; first failure short-circuits.

SQLite handles the concurrent appends without contention. WAL mode lets readers (the viewer, CLI invocations) run without blocking the writer. Writers serialize against each other only during commit (sub-millisecond for single-row inserts). The realistic write rate — one event per stage transition, one per CLI invocation — produces invisible contention.

## Crash recovery

If the runner dies mid-agent (OOM, kill, segfault):

1. **Child Claude processes get reparented to PID 1.** They keep running, but the runner no longer has a handle to them.
2. **The PID file might still exist.** The next runner start checks `kill -0`; if the runner PID is dead, the file is reclaimed.
3. **On restart, the runner replays the event log.** For any `session.started` without a matching `session.ended`, the runner has an orphan to deal with.
4. For each orphan:
   - `kill(pid, 0)` to test liveness.
   - If still alive: emit `session.ended(reason: "runner_restart_orphan")`. Let the retry budget decide. Typically the stage retries with `--resume <uuid>` — Claude's JSONL is intact, so the agent picks up where it left off.
   - If dead: same emission, same handling.

This gives full crash safety without paying for polling in the hot path. The runner only reads the event log on startup; after that, it's event-driven.

### What's NOT recovered

- **In-flight tick state** (e.g. "I've polled CI 3 times so far"). The min_interval starts fresh on restart — you might poll one extra time. Harmless.
- **Hook stdout/stderr from before the crash.** The `hook.fired` event carries a short summary; full output goes to logs. If the runner died before the hook completed, the log entry is lost. The hook just re-runs.
- **Worktree filesystem state.** If the runner died mid-`git worktree add`, you might have a partial worktree. The `setup` stage's `run_shell` will fail on the second attempt because the worktree already exists. Use `stagent goto <task> setup` after manually cleaning up, or add `git worktree remove --force` to your `setup` enter hook for idempotence.

## Reloading config

`SIGHUP` reloads `.stagent.yaml` without restarting:

```bash
kill -HUP $(cat .stagent/runner.pid)
```

Changes apply on the next heartbeat tick. In-flight stages keep their existing hook list until they complete; new entries to any stage use the new config.

This means:

- Edit `max_runs` mid-loop → applies on next entry.
- Add a hook to a stage → applies on next entry.
- Change `flows: default` → existing tasks keep their original flow; new tasks use the new flow.
- Add a new role → available immediately for new sessions.

To pick up a role-prompt edit on an existing session: end the session manually. (Editing the role prompt only affects future sessions; existing sessions have the original prompt baked into their transcript.)

## SwiftUI viewer integration

The Mac viewer is a separate, thin app:

- **Reads SQLite directly** via GRDB. Uses the `tasks` and `sessions` views.
- **Watches `.stagent/stagent.db-wal`** via FSEvents for push refresh. In WAL mode the `-wal` file is touched on every commit. The viewer's reaction is to advance its `last_seen_event_id` cursor and query:
  ```sql
  SELECT * FROM events WHERE id > :cursor ORDER BY id;
  ```
  That's the diff.
- **Writes** by shelling out to the `stagent` CLI (`Process` API).
- **Opens terminals** by shelling out to `osascript` against iTerm/Terminal — e.g. to resume a session in a real Claude Code terminal.

The runner doesn't know the viewer exists. No IPC, no API, no sentinel files. The SQLite file is the contract.

**Liveness:** the viewer checks `.stagent/runner.pid` via `kill -0` to know if the runner is alive. No periodic events needed.

## Per-user, not per-team

The database is per-user, gitignored. Each developer has their own `.stagent/stagent.db` against the same committed config and task files.

Multi-developer collaboration happens through:

- **Pull requests** — for code changes.
- **Shared task files** in `tasks/` — committed, visible to everyone.
- **`.stagent.yaml`** — committed, shared workflow definition.
- **`.stagent/prompts/`** — committed, shared role and stage prompts.

There is intentionally no shared event log. If you want one for archival or team dashboards, point [Litestream](https://litestream.io) at it for read-replicas. Don't try to share a single writer across developers — that breaks the "one writer per DB" assumption WAL mode is built on.

## Tick scheduling

Tick hooks have a `min_interval` (default = heartbeat interval). The runner tracks `last_run_at` per hook and skips hooks whose interval hasn't elapsed. So `wait_for_ci: { min_interval: 30s }` polls every 30s regardless of how often the heartbeat fires.

`stagent poll [<task>]` emits a `force_tick` event the heartbeat sees on its next iteration. For that iteration, tick hooks run **ignoring `min_interval`**. Without args, all active tasks; with a task ID, just that one.

Auto-triggers that emit `force_tick` implicitly:

- `stagent approve <task>` — user might be about to merge; recheck PR state.
- `stagent goto <task> <stage>` — state just changed manually; re-evaluate.

## What the runner does NOT do (in v1)

- **Containerization.** Agents run on the host, inside the task's git worktree, with `--dangerously-skip-permissions`. The worktree provides enough isolation that a misbehaving agent doesn't corrupt the main checkout. Future: a single shared container scoped to "protect the user's machine."
- **GitHub integration as a first-class concept.** GH interaction happens via user-wired `run_shell` hooks calling `gh`. Not via a Go SDK and not via a built-in stage type. v2 may add this.
- **Backgrounding / daemonization.** `stagent run` blocks the terminal. To run in the background: `nohup stagent run &` or use `screen`/`tmux`/`launchd`/`systemd`. v1 won't grow first-class background-mode support; the SwiftUI app will spawn it as a subprocess.
- **Cross-machine coordination.** Per-repo, per-user. If you want to share progress across machines, sync the SQLite file (or run the runner once on a shared host and let everyone view it).
- **Notification (Slack/email/etc.) on stage transitions.** Wire it via a `run_shell` hook on `stage.failed` or similar.

These are intentional cuts. They keep v1 small enough to be correct.
