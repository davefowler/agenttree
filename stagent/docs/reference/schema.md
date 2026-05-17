# Event schema

The SQLite schema that backs the event log, plus the SQL views that project current state.

For the rationale (why event-sourcing, why append-only, why views), see [Concepts → The event log](../concepts/event-log.md) and [`notes/schema.md`](https://github.com/davefowler/stagent/blob/main/notes/schema.md).

## The events table

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

CREATE TRIGGER events_no_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

CREATE TRIGGER events_no_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are append-only'); END;

PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
```

Append-only is enforced by triggers, not just convention. There is no application code path that issues `UPDATE` or `DELETE` against `events`.

## Event types

| Type | `stage` | `role` | Actor | Payload |
|---|---|---|---|---|
| `task.created` | — | — | system | `{title, flow, task_file, worktree_dir, branch}` |
| `task.aborted` | — | — | human | `{reason}` |
| `task.completed` | — | — | system | `{}` |
| `stage.entered` | yes | yes (if agent) | system | `{attempt, reason, stage_type, from_stage?}` |
| `stage.completed` | yes | yes (if agent) | system | `{}` |
| `stage.failed` | yes | yes (if agent) | system | `{reason, last_error}` |
| `session.started` | yes | yes | system | `{claude_session_id, pid}` |
| `session.ended` | yes | yes | system | `{reason, exit_code}` |
| `session.resumed` | yes | yes | system | `{claude_session_id}` |
| `hook.fired` | yes | — | system | `{hook, result, message}` |
| `human.approved` | yes | — | human | `{actor_user}` |
| `force_tick` | (varies) | — | human | `{}` — `task_id` is the task to nudge, or 0 for all-active |

### Payload field reference

#### `task.created`

```json
{
  "title": "Fix login redirect bug",
  "flow": "default",
  "task_file": "tasks/001-fix-login-redirect-bug.md",
  "worktree_dir": "/abs/path/.worktrees/task-001",
  "branch": "task-001"
}
```

The worktree doesn't exist yet at this point — `setup` creates it on the next heartbeat. The path here is the **planned** location.

#### `stage.entered`

```json
{
  "attempt": 2,
  "reason": "redirect",
  "stage_type": "agent",
  "from_stage": "review"
}
```

- `attempt`: 1 on first entry; incremented for retries, redirects, and `human_goto`. This is the value used against `max_runs`.
- `reason`: `flow` (normal forward step) | `retry` (same-stage re-entry within an attempt cycle) | `redirect` (downstream stage routed here) | `human_goto` (user issued `stagent goto`).
- `stage_type`: `agent` | `human` | `script`. Recorded so the `tasks` view doesn't have to read `.stagent.yaml`.
- `from_stage`: set when `reason` is `redirect` or `human_goto`; the previous stage.

#### `stage.failed`

```json
{
  "reason": "budget_exhausted",
  "last_error": "section_check failed: 2/5 items unchecked in 'Implementation plan'"
}
```

#### `session.started`

```json
{
  "claude_session_id": "0193abc4-1234-7890-abcd-ef0123456789",
  "pid": 54321
}
```

#### `session.ended`

```json
{
  "reason": "completed",
  "exit_code": 0
}
```

`reason` values:

- `completed` — child exited 0.
- `crashed` — child exited non-zero.
- `killed` — child killed by signal (runner or external).
- `user_killed` — `stagent restart` killed it deliberately.
- `runner_restart_orphan` — runner restart found an orphan; no liveness info.

#### `hook.fired`

```json
{
  "hook": "section_check",
  "result": "redirect",
  "message": "1 of 3 boxes unchecked in 'Reviews > Pass 1'"
}
```

`result` is one of `pass | not_yet | fail | redirect`. `message` is a short human-readable summary — for full hook output (shell stdout/stderr, etc.), see the runner's logs.

## Views

stagent ships three views by default. They're dropped and recreated on every runner start (cheap; the data isn't in the views, it's computed from `events`).

### `tasks` — current state per task

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

The `waiting_human` branch keys on `payload.stage_type = 'human'` recorded on `stage.entered`. The view never reads `.stagent.yaml`. If config renames a stage's type, the new value lands on the next `stage.entered` and the projection follows automatically.

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

### `active_sessions` — for the runner

```sql
CREATE VIEW active_sessions AS
SELECT s.*
FROM sessions s
WHERE NOT s.ended;
```

## Querying the DB directly

The DB is just SQLite — open it with `sqlite3`, your editor's plugin, [DB Browser for SQLite](https://sqlitebrowser.org/), or anything else:

```bash
sqlite3 .stagent/stagent.db

sqlite> SELECT * FROM tasks WHERE status = 'failed';
sqlite> SELECT * FROM events WHERE task_id = 1 ORDER BY id LIMIT 50;
sqlite> SELECT stage, attempts FROM stage_progress WHERE task_id = 1;
```

In WAL mode, readers don't block writers — query the DB while the runner is running, without coordination.

## Adding new views

A new projection is just a new view:

```sql
CREATE VIEW redirects_per_task AS
SELECT
    task_id,
    SUM(CASE WHEN json_extract(payload, '$.reason') = 'redirect' THEN 1 ELSE 0 END) AS redirect_count
FROM events
WHERE type = 'stage.entered'
GROUP BY task_id;
```

No migration needed; just add the `CREATE VIEW` to the runner's schema bootstrap. On the next runner start, it lands. Old data is automatically covered — views compute over whatever events exist.

## Migration approach

When the event schema or a payload shape changes:

1. **Additive changes** (new event types, new payload fields) require no migration. Old events just don't have the new fields; an upcaster in Go fills in defaults on read.
2. **View changes** are drop-and-recreate on runner start — cheap, no data loss.
3. **Payload reinterpretation** (renaming a field, restructuring) is handled by an upcaster: on read, old payload shapes are translated to current. No DB rewrite.

The events table itself should not need a migration. If it ever does, the migration is "create new DB, replay events from the old one through current handlers."
