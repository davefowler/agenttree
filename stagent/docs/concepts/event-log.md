# The event log

stagent stores **one thing** to disk: a SQLite table of events. The current state of any task is a SQL view over that table.

This page explains why, what's in the log, and what it means for recovery and observability.

## Why an event log

Most workflow tools store "current state" — `task_42.status = "in_progress"`, `task_42.attempts = 3`. To answer "how did this task get here?" you need a separate audit log, kept in sync by application code.

stagent inverts that. The events ARE the state. The "current status" is `SELECT * FROM tasks WHERE id = 42` — a SQL view that scans the events and computes what's true right now.

This buys you:

- **No double-writing.** Emitting an event updates the world. There's no second step where state can drift from history.
- **Time travel for free.** Bug at stage 7? Replay events up to event N and inspect the state then.
- **Audit log built in.** The thing is the audit log.
- **Concurrent writers are trivial.** Append-only with auto-incrementing IDs. No row locks, no MVCC for the writer to worry about.
- **Schema changes are mostly view changes.** Adding a projection doesn't require a migration.

## What's stored

One table:

```sql
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,
    type        TEXT    NOT NULL,
    stage       TEXT    NOT NULL DEFAULT '',
    role        TEXT    NOT NULL DEFAULT '',
    actor       TEXT    NOT NULL,            -- agent | human | heartbeat | system
    payload     TEXT    NOT NULL DEFAULT '{}', -- JSON
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX idx_events_task         ON events(task_id, id);
CREATE INDEX idx_events_type         ON events(type, id);
CREATE INDEX idx_events_task_stage   ON events(task_id, stage, id);

CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

PRAGMA journal_mode = WAL;
```

The append-only guarantee is enforced by SQLite triggers, not just by convention. There is no way to `UPDATE` or `DELETE` an event short of `DROP TABLE`. State corrections happen by **appending corrective events**, never by editing history.

## Event types

| Type | What it represents |
|---|---|
| `task.created` | A new task was registered. Payload: `{title, flow, task_file, worktree_dir, branch}`. |
| `task.aborted` | A task was abandoned. Payload: `{reason}`. |
| `task.completed` | All stages in the flow completed. |
| `stage.entered` | A stage started. Payload: `{attempt, reason, stage_type, from_stage?}`. |
| `stage.completed` | The stage's exit hooks passed (or it redirected — the work was done). |
| `stage.failed` | The stage exhausted its `max_runs` budget. Payload: `{reason, last_error}`. |
| `session.started` | A new Claude session was invoked. Payload: `{claude_session_id, pid}`. |
| `session.ended` | The Claude child process exited. Payload: `{reason, exit_code}`. |
| `session.resumed` | An existing Claude session was resumed. Payload: `{claude_session_id}`. |
| `hook.fired` | A hook ran. Payload: `{hook, result, message}`. |
| `human.approved` | A user ran `stagent approve <task>` on a human stage. |
| `force_tick` | A user ran `stagent poll`. The next tick ignores `min_interval` on tick hooks. |

See [Event schema](../reference/schema.md) for the full payload reference.

## Projections (SQL views)

The interesting state is computed, not stored. Three views ship with stagent:

### `tasks` — current state per task

```sql
SELECT id, title, flow, current_stage, status, worktree_dir, branch,
       created_at, updated_at
FROM tasks;
```

`status` is one of `active | waiting_human | completed | failed | aborted`, computed from the latest `stage.*` event (and its `payload.stage_type`) and any terminal events. The view never reads `.stagent.yaml` — stage type is recorded on every `stage.entered` event so the projection stays decoupled from config.

### `sessions` — latest Claude session per (task, role)

```sql
SELECT task_id, role, claude_id, last_stage, last_used_at, ended, end_reason
FROM sessions;
```

Used by the runner to know which session UUID to `--resume` for a given `(task, role)`.

### `stage_progress` — attempts and status per (task, stage)

```sql
SELECT task_id, stage, attempts, status, last_event_at
FROM stage_progress;
```

Used to enforce `max_runs` and to surface "stage X attempted N times" in the UI.

## Append-only in practice

You'd think append-only would feel restrictive. In practice, every state change you'd want to express maps cleanly to "append an event."

| What you'd UPDATE in a normal schema | What you append instead |
|---|---|
| `task.status = 'completed'` | `task.completed` event |
| `stage.attempts = stage.attempts + 1` | `stage.entered` event with `reason: retry` |
| `task.worktree_dir = '/new/path'` | `task.moved` event (if you ever needed this) |
| `session.ended = true` | `session.ended` event |

There is no `events.update`, no `events.delete`. The triggers will refuse.

## Recovery

The runner is restartable. If it dies (OOM, kill, segfault), restart it and:

1. It reads the event log and computes current state.
2. For any `(task, stage)` with `session.started` but no `session.ended`, it checks `kill(pid, 0)`. If alive, it emits `session.ended` with `reason: "runner_restart_orphan"` and lets the retry budget handle it. If dead, same thing.
3. The next heartbeat picks tasks back up where they left off.

No partial state to reconcile, no cleanup script, no migrations. The log is the truth.

## What's NOT in the event log

- **Document contents.** Task files (`tasks/<id>-<slug>.md`) live on disk and are committed to git. The log references the path, not the content.
- **Claude session transcripts.** Stored under `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl` by Claude Code itself. The log records the UUID; `--resume <uuid>` re-attaches.
- **Hook output verbatim.** `hook.fired` carries `{hook, result, message}` — the verdict and a short human-readable message, not full stdout/stderr. Long output goes to logs (Go's `slog`) for debugging.
- **Project configuration.** `.stagent.yaml` is loaded at runner start and on `SIGHUP`. The runtime uses an in-memory representation; nothing in the event log embeds the config.

## Database location

Per-user, gitignored. `.stagent/stagent.db` (plus the WAL/SHM files). Each developer has their own log against the same checked-in tasks and config. Multi-dev collaboration happens through PRs (the code) and the shared task files in `tasks/`, not through a shared event log.

If you want cross-machine sync of your personal log, point [Litestream](https://litestream.io) at it. Time Machine, rsync, or your tool of choice. The DB is a single file plus WAL.

## Push signal for viewers

No sentinel files, no API. The SwiftUI viewer (and any other read-only consumer) watches `.stagent/stagent.db-wal` with FSEvents. In WAL mode, that file is touched on every commit. The viewer advances its `last_seen_event_id` cursor and runs:

```sql
SELECT * FROM events WHERE id > :cursor ORDER BY id;
```

That's the diff. The viewer also re-queries the `tasks` view to refresh its list. Runner liveness comes from `.stagent/runner.pid` — not from periodic events.

## Migrations

When schemas change:

- **Additive changes** (new event types, new payload fields) require no migration. Old events just don't have the new fields; the upcaster (in Go) supplies defaults on read.
- **View changes** are dropped and recreated on runner startup — cheap, no data loss.
- **Payload reinterpretation** is handled by an upcaster: on read, old payload shapes are translated to current. No DB rewrite.

The events table itself should not need a migration. If it ever does, the migration is "create new DB, replay events from the old one through current handlers."
