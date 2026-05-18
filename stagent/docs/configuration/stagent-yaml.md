# The `.stagent.yaml` file

Single file. Declares roles, stages, flows, hooks, and (optionally) commands. Loaded once at runner start and on `SIGHUP`.

The version `stagent init` emits lives at [`scaffold/.stagent.yaml`](https://github.com/davefowler/stagent/blob/main/scaffold/.stagent.yaml) and is the best place to start. This page documents every field.

## Full example

```yaml
project: my-project

# ─── Roles ────────────────────────────────────────────────────────────
roles:
  developer:
    model: opus
    dangerous: true     # passes --dangerously-skip-permissions; required v1
    bound: task         # one session per (task, role)

  reviewer:
    model: sonnet
    dangerous: true
    bound: stage        # fresh session each review pass

# ─── Tasks ────────────────────────────────────────────────────────────
tasks_dir: tasks         # default; configurable

# ─── Stages ───────────────────────────────────────────────────────────
stages:

  setup:
    type: script
    max_runs: 3
    hooks:
      enter:
        - run_shell:
            cmd: "git worktree add {{.Task.WorktreeDir}} -b {{.Task.Branch}} origin/main"
            fail_on_nonzero: true

  code:
    type: agent
    role: developer
    max_runs: 7
    hooks:
      enter:
        - run_shell:
            cmd: "cd {{.Task.WorktreeDir}} && git rebase origin/main"
            fail_on_nonzero: true
      exit:
        - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && go test ./...", fail_on_nonzero: true }
        - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && go vet ./...",  fail_on_nonzero: true }
        - section_check:
            section: "Implementation plan"
            expect: all_checked

  pr:
    type: script
    max_runs: 5
    hooks:
      enter:
        - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && git push -u origin HEAD" }
        - run_shell:
            cmd: "cd {{.Task.WorktreeDir}} && gh pr create --fill || true"
            fail_on_nonzero: false
      tick:
        - wait_for_ci: { min_interval: 30s, timeout: 30m }
      exit:
        - ci_status:
            on_failure:
              redirect_to: code
              message_template: |
                CI failed. Failing checks:
                {{.CIFailures}}
                See logs at {{.CILogURL}}. Fix and push again.

  review:
    type: agent
    role: reviewer
    max_runs: 3
    hooks:
      exit:
        - section_check:
            section: "Reviews > /^Pass \\d+$/[-1]"
            expect: all_checked
            on_fail:
              redirect_to: code
              message_from_section: "Reviews > /^Pass \\d+$/[-1]"

  human_review:
    type: human
    hooks:
      tick:
        - wait_for_merge: { min_interval: 1m, timeout: 24h }
        - ci_status:
            min_interval: 5m
            on_failure:
              redirect_to: code
              message_template: "CI went red during human review. Failing: {{.CIFailures}}"

  cleanup:
    type: script
    max_runs: 1
    hooks:
      exit:
        - run_shell: { cmd: "git worktree remove {{.Task.WorktreeDir}}" }
        - run_shell:
            cmd: "git branch -D {{.Task.Branch}} 2>/dev/null || true"
            fail_on_nonzero: false

# ─── Flows ────────────────────────────────────────────────────────────
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

# ─── Commands ─────────────────────────────────────────────────────────
commands:
  ship:
    desc: Approve current human stage and push
    run: |
      stagent approve {{.Task.ID}}
      git -C {{.Task.WorktreeDir}} push

  resume:
    desc: Resume the developer's session in a real Claude Code terminal
    run: |
      SID=$(stagent session {{.Task.ID}} developer)
      cd {{.Task.WorktreeDir}} && claude --resume "$SID"

# ─── Heartbeat ────────────────────────────────────────────────────────
heartbeat:
  interval: 2s
```

## Top-level fields

### `project`

A label for this project. Used in log output and the SwiftUI viewer. Not used for anything functional.

### `roles`

Map of role name → role definition. Roles are referenced from `agent` stages via `role:`.

```yaml
roles:
  <name>:
    model: opus | sonnet | haiku
    dangerous: true               # required true in v1; passes --dangerously-skip-permissions
    bound: task | stage           # session scope; default "task"
```

Role *prompts* (system prompts) live at `.stagent/prompts/roles/<name>.md` by convention. There's no per-role prompt path override — the name is the identifier.

See [Prompts](prompts.md) and [Sessions](../concepts/sessions.md) for details.

### `tasks_dir`

Where task files live. Default: `tasks`. The directory is committed; new task files are created here by `stagent new`.

### `stages`

Map of stage name → stage definition. Each stage has:

```yaml
<name>:
  type: agent | human | script    # required
  role: <role-name>               # required if type: agent; forbidden otherwise
  max_runs: <int>                 # default: 3 (agent/script), 1 (human)
  hooks:
    enter: [...]                  # optional list of hooks
    exit:  [...]                  # optional list of hooks
    tick:  [...]                  # optional; only on script + human
```

**Stage names are bare identifiers** (`code`, not `implement.code`). They double as path keys for prompts (`.stagent/prompts/stages/<name>.md`).

See [Stages, flows, hooks](../concepts/stages-flows-hooks.md) for what each type does.

### `flows`

Map of flow name → ordered list of stage names. The `default` flow is what `stagent new "<title>"` uses unless `--flow <name>` is passed.

```yaml
flows:
  default:
    - setup
    - code
    - pr
    - review
    - human_review
    - cleanup
```

A flow is just a list. There are no nested flows, no conditional flows, no branching syntax — branches happen at runtime via hook redirects.

See [Custom flows](../patterns/custom-flows.md) for adding your own.

### `commands`

Optional. User recipes — like [`just`](https://github.com/casey/just) — that run shell commands with task context templated in:

```yaml
commands:
  ship:
    desc: Approve current human stage and push
    run: |
      stagent approve {{.Task.ID}}
      git -C {{.Task.WorktreeDir}} push
```

Invoked as `stagent ship <task-id>`. Templated with the [task projection](../reference/schema.md#tasks-current-state-per-task) — fields available: `.Task.ID`, `.Task.Title`, `.Task.Branch`, `.Task.WorktreeDir`, `.Task.Flow`, `.Task.CurrentStage`, `.Task.Status`.

Keep commands short. Anything more than a few lines should probably be a built-in Go command instead.

### `heartbeat`

```yaml
heartbeat:
  interval: 2s
```

How often the runner ticks. Default is `2s`. Lower it (e.g. `500ms`) for snappier transitions during demos; raise it (e.g. `10s`) for low-traffic projects. Hook `min_interval` is independent — a hook with `min_interval: 30s` runs every 30s regardless of how often the heartbeat ticks.

## Schema rules

- **Stage names are bare identifiers.** They key the prompt path (`prompts/stages/<name>.md`). They do NOT key per-stage files in `tasks_dir/` — there's one task file per task, shared by all stages.
- **One task file per task** at `<tasks_dir>/<id>-<slug>.md` (committed). Sections within it represent stage outputs. Hooks reference section paths.
- **`type` is required** on every stage. One of `agent`, `human`, `script`.
- **`role` is required** on `agent` stages. Forbidden on `human` and `script`.
- **No `output:`, `skill:`, `template:`, or per-stage path overrides.** Everything is by convention or by section reference.
- **`max_runs`** is the total times this stage may be entered across the task (any reason — initial flow, retry, redirect, human_goto). Defaults: 3 for agent/script, 1 for human.
- **`hooks.tick` is valid** on `script` and `human` stages. NOT on `agent` stages — agents own their own turn. On human stages, tick hooks run while waiting (use `min_interval` to avoid hot-polling).
- **The agent never signals completion explicitly.** When its process exits (any reason), the runner runs exit hooks. Encode "is this done?" by writing exit hooks — typically `section_check` on a section in the task file.
- **Hooks return one of four verdicts:** `Pass`, `NotYet` (tick only), `Fail`, `Redirect(stage, message)`.
- **A stage with tick hooks completes** when all tick hooks return `Pass` on the same tick AND exit hooks then pass.
- **Human stages complete** via EITHER `stagent approve <task>` OR all tick hooks returning `Pass`. Whichever fires first.

## Reloading

The runner watches `.stagent.yaml` and reloads on `SIGHUP`. To reload without restart:

```bash
kill -HUP $(cat .stagent/runner.pid)
```

Changes apply on the next heartbeat tick. In-flight stages keep their existing hook list until they complete; new stages picked up after reload use the new config.

This means: if you edit `max_runs` while a stage is mid-retry-loop, the change takes effect on the next stage entry, not retroactively. Same with adding/removing hooks — in-flight evaluations finish under the old rules.
