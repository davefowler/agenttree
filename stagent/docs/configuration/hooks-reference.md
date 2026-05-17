# Hooks reference

Every hook stagent ships in v1, with arguments, slots, and verdicts.

Hooks are declared inside a stage's `hooks:` map in `.stagent.yaml`:

```yaml
stages:
  code:
    type: agent
    role: developer
    hooks:
      enter: [...]       # list of hooks; run once on entry
      exit:  [...]       # list of hooks; run on completion attempt
      tick:  [...]       # list of hooks; run every heartbeat (script + human only)
```

A hook line is a tagged-union: the key is the hook name, the value is the args map.

```yaml
- run_shell:
    cmd: "go test ./..."
    fail_on_nonzero: true
    timeout: 5m
```

## Common args

These apply to every hook unless noted otherwise:

| Arg | Type | Default | Meaning |
|---|---|---|---|
| `min_interval` | duration | 0 (every tick) | For `tick` hooks: minimum time between runs. Ignored for `enter`/`exit`. |
| `file` | string | `{{.TaskFile}}` | For section-reading hooks: which file to read. Defaults to the task file. |
| `on_fail` | object | none | For validators: override the default `Fail` verdict with a `Redirect`. See `section_check` example. |

## Hooks

### `run_shell`

Run a shell command. Pass if exit code 0; behavior on non-zero is configurable.

```yaml
- run_shell:
    cmd: "cd {{.Task.WorktreeDir}} && go test ./..."
    fail_on_nonzero: true     # default true: non-zero → Fail
    timeout: 5m               # default: 5 minutes
```

| Slot | Use case |
|---|---|
| `enter` | Setup (worktree creation, dependency install). |
| `exit` | Validation (tests, lint, format check). |
| `tick` | Polling external state — but prefer purpose-built hooks like `wait_for_ci` when available. |

**Args:**

- `cmd` *(required)*: shell command, templated with task context.
- `fail_on_nonzero` *(default `true`)*: if `false`, non-zero exit still passes the hook. Useful for "best-effort" actions (`gh pr create --fill || true`).
- `timeout` *(default `5m`)*: kill the process and `Fail` if it runs longer.

Stdout/stderr go to the runner's logs (Go `slog`), NOT to the `hook.fired` event (the payload only carries verdict + short message).

### `section_check`

Verify checkboxes (or content) in a task-file section.

```yaml
- section_check:
    section: "Implementation plan"
    expect: all_checked
```

```yaml
- section_check:
    section: "Reviews > Pass [-1]"
    expect: all_checked
    on_fail:
      redirect_to: code
      message_from_section: "Reviews > Pass [-1]"
```

| Slot | Use case |
|---|---|
| `exit` | Verifying agent output. Always `exit`. |

**Args:**

- `section` *(required)*: section path. See [Task files → section path syntax](task-files.md#section-path-syntax-used-by-hooks). Supports `[-1]` modifier.
- `expect` *(required)*: `all_checked` is the only value in v1.
- `file` *(default `{{.TaskFile}}`)*: which file to read.
- `on_fail` *(optional)*: instead of returning `Fail`, return `Redirect(to, message)`.
  - `redirect_to` *(required if `on_fail` is set)*: target stage name.
  - `message_from_section` *(optional)*: the redirect message is the body of this section path (supports `[-1]`). Defaults to the same `section`.
  - `message_template` *(optional)*: alternative to `message_from_section`; a templated string.

If the section doesn't exist, `section_check` returns `Fail` with a "section not found" message.

### `min_words`

Verify a section has at least N words.

```yaml
- min_words:
    section: "Code > Notes"
    min: 30
```

| Slot | Use case |
|---|---|
| `exit` | Anti-empty-section guard. |

**Args:**

- `section` *(required)*: section path.
- `min` *(required)*: minimum word count.
- `file` *(default `{{.TaskFile}}`)*: which file to read.

Useful for stages that should produce real prose, not just bullet lists.

### `section_redirect`

Redirect when a specific checkbox is checked. (Inverse of `section_check`'s `on_fail`.)

```yaml
- section_redirect:
    section: "Decisions > Verdict"
    when_checked: "Needs design review"
    redirect_to: design_review
    message_from_section: "Decisions > Notes"
```

| Slot | Use case |
|---|---|
| `exit` | Routing primitive when "the agent's verdict picks the next stage." |

**Args:**

- `section` *(required)*: section path containing the checkbox to inspect.
- `when_checked` *(required)*: literal text of the checkbox label. If that box is checked, redirect.
- `redirect_to` *(required)*: target stage.
- `message_from_section` *(optional)*: section path whose body becomes the redirect message.
- `file` *(default `{{.TaskFile}}`)*: which file to read.

If `when_checked` is not checked, the hook returns `Pass`. If the section doesn't exist, returns `Fail`.

### `wait_for_ci`

Poll the GitHub Actions status for the current branch's PR.

```yaml
- wait_for_ci:
    min_interval: 30s
    timeout: 30m
```

| Slot | Use case |
|---|---|
| `tick` | Always tick. |

**Args:**

- `min_interval` *(default `30s`)*: how often to actually poll (not just check tick).
- `timeout` *(default `30m`)*: after this duration with no result, return `Fail`.

**Verdicts:**

- Still running → `NotYet`.
- All checks green → `Pass`.
- Any required check red → `Pass` (don't redirect — let `ci_status` decide on exit).
- Timeout → `Fail`.

This hook only WAITS. To act on CI failure (redirect to code), pair it with `ci_status` in `exit`.

### `ci_status`

Check the current CI state for the branch and act on failures.

```yaml
- ci_status:
    on_failure:
      redirect_to: code
      message_template: |
        CI failed. Failing checks:
        {{.CIFailures}}
        See logs at {{.CILogURL}}. Fix and push again.
```

| Slot | Use case |
|---|---|
| `exit` (on `script` stages) | After `wait_for_ci` resolves, evaluate the result. |
| `tick` (on `human` stages) | Guard human_review against CI going red mid-wait. |

**Args:**

- `min_interval` *(tick only; default 5m)*: poll frequency.
- `on_failure.redirect_to` *(required)*: target stage when CI is red.
- `on_failure.message_template` *(optional)*: templated message. Available extras: `{{.CIFailures}}` (newline-separated list), `{{.CILogURL}}` (the run's GitHub URL).

**Verdicts:**

- CI green → `Pass`.
- CI red → `Redirect(on_failure.redirect_to, formatted_message)`.
- CI pending → `NotYet` (tick) / `Fail` (exit). On `exit`, this shouldn't normally happen — pair with `wait_for_ci`.

### `wait_for_merge`

Poll the GitHub PR for merged status.

```yaml
- wait_for_merge:
    min_interval: 1m
    timeout: 24h
```

| Slot | Use case |
|---|---|
| `tick` (on `human` stages) | The "auto-complete on merge" path. |

**Args:**

- `min_interval` *(default `1m`)*: poll frequency.
- `timeout` *(default `24h`)*: after this duration, return `Fail`.

**Verdicts:**

- PR open → `NotYet`.
- PR merged → `Pass`.
- PR closed without merge → `Fail`.
- Timeout → `Fail`.

## Hook return-value cheat sheet

| Verdict | Where it's valid | What happens |
|---|---|---|
| `Pass` | enter, exit, tick | This hook is satisfied. Stage proceeds when all hooks at this slot pass. |
| `NotYet` | tick only | Keep ticking; check again on the next heartbeat (subject to `min_interval`). |
| `Fail` | enter, exit, tick | Retry the stage or fail it. Hook's `message` becomes the agent's next prompt. |
| `Redirect(target, message)` | enter, exit, tick | Route to `target`. Loop-backs (review → code) are redirects. |

## Writing a new hook

Adding a hook is ~20 lines + a test. The interface:

```go
type Hook interface {
    Run(ctx *HookCtx) HookResult
    MinInterval() time.Duration
}

type HookCtx struct {
    Task        TaskProjection
    Stage       string
    Slot        Slot              // Enter | Exit | Tick
    TaskFile    string
    Now         time.Time
    LastRunAt   time.Time         // tick hooks only
}

type HookResult struct {
    Verdict Verdict
    Target  string
    Message string
}
```

Register the hook in `cmd/stagent/hooks/registry.go` and add an `init()` function that maps the YAML key (`my_new_hook`) to the constructor.

The YAML form is a tagged union: parse the args from `map[string]any` in your constructor, returning a usage error if required fields are missing.

See [`notes/architecture.md`](https://github.com/davefowler/stagent/blob/main/notes/architecture.md) for the design rationale (why hooks are interfaces, why verdicts are this small set, why agents don't run hooks themselves).
