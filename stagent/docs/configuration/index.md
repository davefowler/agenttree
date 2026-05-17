# Configuration

stagent is configured by four kinds of file, all committed to git:

| File | What goes in it | When loaded |
|---|---|---|
| `.stagent.yaml` | Roles, stages, flows, hooks, commands. | Runner start; on `SIGHUP`. |
| `.stagent/prompts/roles/<role>.md` | System prompt for a role (identity, project context). Plain markdown. | First Claude invocation per `(task, role)`; once per session. |
| `.stagent/prompts/stages/<stage>.md` | User message for entering a stage. Templated. | Every entry to an agent stage. |
| `.stagent/templates/task.md` | Optional template for `stagent new "<title>"`. Templated. | Only when creating a task from a title. |

Task files themselves (`tasks/<id>-<slug>.md`) are user-written, not configuration — see [Task files](task-files.md).

## Layout

After `stagent init`:

```
.stagent.yaml                          # COMMITTED — workflow config

tasks/                                 # COMMITTED — one markdown per task
  001-fix-login-redirect.md
  002-add-user-export.md

.stagent/
  prompts/                             # COMMITTED — workflow definition
    roles/
      developer.md                     # role system prompts
      reviewer.md
    stages/
      code.md                          # stage user prompts (templated)
      review.md
  templates/
    task.md                            # COMMITTED — task template (optional)

  stagent.db                           # GITIGNORED — per-dev event log
  stagent.db-wal                       # GITIGNORED
  stagent.db-shm                       # GITIGNORED
  runner.pid                           # GITIGNORED — runner liveness
```

`.gitignore` snippet (`stagent init` appends this):

```
.stagent/stagent.db*
.stagent/runner.pid
.worktrees/
```

## In this section

- **[The `.stagent.yaml` file](stagent-yaml.md)** — the workflow config, walked through field-by-field.
- **[Task files](task-files.md)** — the markdown shape: sections, checkboxes, the Pass-N review pattern.
- **[Prompts](prompts.md)** — role prompts vs. stage prompts, templating, examples.
- **[Hooks reference](hooks-reference.md)** — every built-in hook with arguments and examples.
