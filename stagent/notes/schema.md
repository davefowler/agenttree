# Schema

SQLite. One table you write to. Everything else is a view.

## The table

```sql
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,
    type        TEXT    NOT NULL,
    stage       TEXT    NOT NULL DEFAULT '',   -- '' for task-level events
    role        TEXT    NOT NULL DEFAULT '',   -- '' when N/A
    actor       TEXT    NOT NULL,              -- agent | human | heartbeat | system
    payload     TEXT    NOT NULL DEFAULT '{}', -- JSON
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

CREATE INDEX idx_events_task         ON events(task_id, id);
CREATE INDEX idx_events_type         ON events(type, id);
CREATE INDEX idx_events_task_stage   ON events(task_id, stage, id);

-- Enforce append-only at the lowest level. Future contributors cannot
-- accidentally violate the invariant.
CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

-- WAL mode for concurrent readers (SwiftUI viewer, multiple CLI invocations).
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
```

That's it. The table is INSERT-only — no UPDATE, no DELETE, ever. State corrections happen by appending corrective events. This is enforced by triggers, not just convention.

**Why append-only works locking-wise.** SQLite in WAL mode lets readers run without blocking writers, and writers serialize against each other only during the commit (sub-millisecond for single-row inserts). Since we never UPDATE, there are no row-update conflicts. The realistic write rate — one event per agent transition, one per CLI invocation — produces invisible contention.

### Event types

| Type | `stage` | `role` | Payload |
|---|---|---|---|
| `task.created` | — | — | `{title, flow, worktree_dir, branch}` |
| `task.aborted` | — | — | `{reason}` |
| `task.completed` | — | — | `{}` |
| `stage.entered` | yes | yes (if agent) | `{attempt, reason, stage_type, from_stage?}` — reason ∈ `flow`/`retry`/`redirect`/`human_goto`; stage_type ∈ `agent`/`human`/`script` |
| `stage.completed` | yes | yes (if agent) | `{}` |
| `stage.failed` | yes | yes (if agent) | `{reason, last_error}` |
| `session.started` | yes | yes | `{claude_session_id, pid}` |
| `session.ended` | yes | yes | `{reason, exit_code}` |
| `session.resumed` | yes | yes | `{claude_session_id}` |
| `hook.fired` | yes | — | `{hook, result, message}` |
| `human.approved` | yes | — | `{actor_user}` |
| `force_tick` | — | — | `{}` — task_id is set if scoped to one task, else 0 for all-active. Causes the next heartbeat iteration to ignore min_interval on tick hooks. |

## Views

### `tasks` — current state of every task

```sql
CREATE VIEW tasks AS
WITH
  created AS (
    SELECT
        task_id,
        json_extract(payload, '$.title')        AS title,
        json_extract(payload, '$.flow')         AS flow,
        json_extract(payload, '$.worktree_dir') AS worktree_dir,
        json_extract(payload, '$.branch')       AS branch,
        created_at                              AS created_at
    FROM events WHERE type = 'task.created'
  ),
  latest_stage AS (
    SELECT task_id, stage, MAX(id) AS evt_id
    FROM events
    WHERE type IN ('stage.entered', 'stage.completed', 'stage.failed')
    GROUP BY task_id
  ),
  latest_stage_event AS (
    SELECT
        e.task_id,
        e.stage,
        e.type,
        e.created_at,
        json_extract(e.payload, '$.stage_type') AS stage_type
    FROM events e
    JOIN latest_stage ls ON e.id = ls.evt_id
  ),
  terminal AS (
    SELECT task_id, type, created_at
    FROM events
    WHERE type IN ('task.completed', 'task.aborted')
  )
SELECT
    c.task_id                                          AS id,
    c.title,
    c.flow,
    c.worktree_dir,
    c.branch,
    COALESCE(lse.stage, '')                            AS current_stage,
    CASE
        WHEN t.type = 'task.completed'       THEN 'completed'
        WHEN t.type = 'task.aborted'         THEN 'aborted'
        WHEN lse.type = 'stage.failed'       THEN 'failed'
        WHEN lse.type = 'stage.entered'
         AND lse.stage_type = 'human'        THEN 'waiting_human'
        ELSE 'active'
    END                                                AS status,
    c.created_at,
    COALESCE(lse.created_at, c.created_at)             AS updated_at
FROM created c
LEFT JOIN latest_stage_event lse USING (task_id)
LEFT JOIN terminal           t   USING (task_id);
```

The `waiting_human` branch keys on `payload.stage_type = 'human'` recorded on `stage.entered`. The view never reads `.stagent.yaml`. If a config rename ever changes a stage's `type`, the new value lands on the next `stage.entered` and the projection follows.

### `sessions` — latest Claude session per (task, role)

```sql
CREATE VIEW sessions AS
WITH ranked AS (
    SELECT
        task_id, role, stage,
        json_extract(payload, '$.claude_session_id') AS claude_id,
        type, created_at,
        ROW_NUMBER() OVER (
            PARTITION BY task_id, role
            ORDER BY id DESC
        ) AS rn
    FROM events
    WHERE type IN ('session.started', 'session.resumed', 'session.ended')
)
SELECT
    r.task_id,
    r.role,
    -- latest claude_id we saw start/resume for this (task, role)
    (
        SELECT json_extract(e.payload, '$.claude_session_id')
        FROM events e
        WHERE e.task_id = r.task_id AND e.role = r.role
          AND e.type IN ('session.started', 'session.resumed')
        ORDER BY e.id DESC LIMIT 1
    )                                                  AS claude_id,
    r.stage                                            AS last_stage,
    r.created_at                                       AS last_used_at,
    (r.type = 'session.ended')                         AS ended,
    CASE
        WHEN r.type = 'session.ended'
        THEN json_extract(
            (SELECT payload FROM events WHERE id = (
                SELECT MAX(id) FROM events
                WHERE task_id = r.task_id AND role = r.role AND type = 'session.ended'
            )),
            '$.reason'
        )
        ELSE NULL
    END                                                AS end_reason
FROM ranked r
WHERE r.rn = 1;
```

### `stage_progress` — attempts and status per (task, stage)

```sql
CREATE VIEW stage_progress AS
SELECT
    task_id,
    stage,
    SUM(CASE WHEN type = 'stage.entered' THEN 1 ELSE 0 END) AS attempts,
    CASE
        WHEN MAX(CASE WHEN type = 'stage.completed' THEN id END) >
             COALESCE(MAX(CASE WHEN type = 'stage.entered' THEN id END), 0)
        THEN 'completed'
        WHEN MAX(CASE WHEN type = 'stage.failed' THEN id END) >
             COALESCE(MAX(CASE WHEN type = 'stage.entered' THEN id END), 0)
        THEN 'failed'
        WHEN MAX(CASE WHEN type = 'stage.entered' THEN id END) IS NOT NULL
        THEN 'in_progress'
        ELSE 'not_started'
    END AS status,
    MAX(created_at) AS last_event_at
FROM events
WHERE stage != ''
GROUP BY task_id, stage;
```

### `active_sessions` — for the heartbeat to know what's running

```sql
CREATE VIEW active_sessions AS
SELECT s.*
FROM sessions s
WHERE NOT s.ended;
```

## Why views, not tables

- **No double-writing.** Emitting an event updates the world. There's no second step where state can drift.
- **Time travel for free.** Bug at stage 7? Replay events up to event N and inspect the state then.
- **Audit log built in.** The thing is the audit log.
- **Concurrent writers are trivial.** Append-only with auto-increment IDs. No row locks.
- **Schema changes are mostly view changes.** Adding a projection doesn't require a migration.

## Migration approach

When the event schema or a payload shape changes:

1. **Additive changes** (new event types, new payload fields) require no migration. Old events just don't have the new fields.
2. **View changes** are dropped and recreated on runner startup — cheap, no data loss.
3. **Payload reinterpretation** (renaming a field, restructuring) is handled by an upcaster in Go: on read, old payload shapes are translated to current. No DB rewrite.

The events table itself should not need a migration. If it ever does, the migration is "create new DB, replay events from the old one through current handlers."

## Push signal for the viewer

No sentinel file, no API. The SwiftUI viewer watches `.stagent/stagent.db-wal` with FSEvents — in WAL mode that file is touched on every commit. On change, the viewer advances its "last seen event id" cursor and runs:

```sql
SELECT * FROM events WHERE id > :cursor ORDER BY id;
```

That's the diff. The viewer also re-queries the `tasks` view to refresh its list. Runner liveness comes from a PID file at `.stagent/runner.pid` — not from periodic events.
