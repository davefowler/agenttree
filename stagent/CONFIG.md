# Config (`.stagent.yaml`)

Single file. Declares roles, stages, flows, hooks, and optional commands. Loaded once at daemon start and on `SIGHUP`.

## Full example

```yaml
project: my-project

# ─── Roles ────────────────────────────────────────────────────────────
# Who can do work. Role prompt is loaded by convention from
# .stagent/prompts/roles/<name>.md — no per-role override.
# v1: no containers. Agents run on the host in the task's git worktree.
roles:
  developer:
    model: opus
    dangerous: true     # passes --dangerously-skip-permissions to claude -p
                        # required true for agent roles in v1 (headless mode)

  reviewer:
    model: sonnet
    dangerous: true

# ─── Stages ───────────────────────────────────────────────────────────
# Three types: agent, human, script.
#
# Conventions (no overrides in YAML):
#   - artifact:       .stagent/tasks/<task_id>/<stage>.md
#   - template:       .stagent/templates/stages/<stage>.md
#   - stage prompt:   .stagent/prompts/stages/<stage>.md
#   - role prompt:    .stagent/prompts/roles/<role>.md
#
# max_runs is the total entries to a stage across the task's lifetime
# (initial + retries + redirects + human_gotos). Defaults: 3 (agent/script), 1 (human).
stages:

  define:
    type: agent
    role: developer
    max_runs: 2
    hooks:
      enter:
        - create_from_template: {}
      exit:
        - file_exists: {}                                              # checks tasks/<id>/define.md
        - min_words: { section: Approach, min: 50 }
        - section_check: { section: Completion, expect: all_checked }

  plan:
    type: agent
    role: developer
    max_runs: 2
    hooks:
      enter:
        - create_from_template: {}
      exit:
        - file_exists: {}
        - section_check: { section: Completion, expect: all_checked }

  plan_review:
    type: human
    # stagent approve is the signal; no hooks needed

  code:
    type: agent
    role: developer
    max_runs: 7    # generous: review and ci both redirect back here
    hooks:
      enter:
        - run_shell: { cmd: "git rebase origin/main", fail_on_nonzero: false }
        - create_from_template: {}
      exit:
        - run_shell: { cmd: "go test ./...", fail_on_nonzero: true }
        - run_shell: { cmd: "go vet ./...",  fail_on_nonzero: true }
        - section_check: { section: Completion, expect: all_checked }
        - run_shell: { cmd: "git push -u origin HEAD", fail_on_nonzero: true }
        - run_shell: { cmd: "gh pr create --fill || true", fail_on_nonzero: false }

  review:
    type: agent
    role: reviewer
    max_runs: 3
    hooks:
      enter:
        - create_from_template: {}
      exit:
        - file_exists: {}
        - section_check: { section: Verdict, expect: all_checked }
        - section_redirect:
            when_checked: "Request changes"
            redirect_to: code
            message_from_section: "Changes requested"

  ci:
    type: script
    max_runs: 3
    hooks:
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

  human_review:
    type: human
    # Reviewer eyeballs PR + approves. Merge happens in the GitHub UI
    # (or wire a `gh pr merge` run_shell on exit if you want auto-merge).

  merge_wait:
    type: script
    max_runs: 1
    hooks:
      tick:
        - wait_for_merge: { min_interval: 30s, timeout: 24h }

  cleanup:
    type: script
    max_runs: 1
    hooks:
      exit:
        - run_shell: { cmd: "git worktree remove {{.Task.WorktreeDir}}" }
        - run_shell: { cmd: "git branch -D {{.Task.Branch}} 2>/dev/null || true", fail_on_nonzero: false }
        - run_shell: { cmd: "mkdir -p .stagent/archive && mv .stagent/tasks/{{.Task.ID}} .stagent/archive/{{.Task.ID}}" }

# ─── Flows ────────────────────────────────────────────────────────────
# Ordered lists of stage names. A task picks one at creation time.
flows:
  default:
    - define
    - plan
    - plan_review
    - code
    - review
    - ci
    - human_review
    - merge_wait
    - cleanup

  quick:
    - define
    - code
    - cleanup

# ─── Commands ─────────────────────────────────────────────────────────
# User recipes — like `just`. Templated with the task projection.
# Keep them short. Anything complex belongs as a Go command.
commands:
  ship:
    desc: Approve current human stage and push
    run: |
      stagent approve {{.Task.ID}}
      git -C {{.Task.WorktreeDir}} push

  open:
    desc: Open the task's worktree in iTerm
    run: open -a iTerm {{.Task.WorktreeDir}}

  resume:
    desc: Resume the developer's session in a new Claude Code terminal
    run: |
      SID=$(stagent session {{.Task.ID}} developer)
      osascript -e 'tell application "iTerm" to create window with default profile' \
                -e "tell application \"iTerm\" to tell current window to tell current session to write text \"cd {{.Task.WorktreeDir}} && claude --resume $SID\""

# ─── Heartbeat ────────────────────────────────────────────────────────
heartbeat:
  interval: 2s          # how often the daemon ticks
```

## Schema rules

- **Stage names are bare identifiers** and are the universal key — they name the prompt (`prompts/stages/<name>.md`), the template (`templates/stages/<name>.md`), and the artifact (`tasks/<id>/<name>.md`).
- **`type` is required** on every stage. One of `agent`, `human`, `script`.
- **`role` is required** on `agent` stages. Forbidden on `human` and `script`.
- **No `output:` field.** Artifact name follows the stage name. Want a different filename? Rename the stage.
- **No `skill:` or per-stage prompt path field.** Prompts are loaded by convention.
- **`max_runs`** is the total times this stage may be entered across the task (any reason — initial, retry, redirect, human_goto). Defaults: 3 for `agent`/`script`, 1 for `human`.
- **`hooks.tick` is only valid** on `type: script` stages.
- **The agent never signals completion explicitly.** When its process exits (any reason), the daemon runs the exit hooks. Encode "is this done?" by writing exit hooks — typically `section_check` on a Completion section in the artifact.
- **Hooks return one of three verdicts:** `Pass` (proceed), `Fail` (retry-or-fail), `Redirect(stage, message)` (route to chosen stage; loops happen this way).

## Hooks reference (v1)

| Hook | Args | When |
|---|---|---|
| `file_exists` | `path?` (defaults to `tasks/<id>/<stage>.md`) | exit |
| `min_words` | `section, min, file?` | exit |
| `section_check` | `section, expect: all_checked, file?` | exit |
| `section_redirect` | `when_checked, redirect_to, message_from_section?, file?` | exit |
| `create_from_template` | `template?, dest?` (both default by convention) | enter |
| `run_shell` | `cmd, fail_on_nonzero, timeout` | enter / exit |
| `wait_for_ci` | `min_interval, timeout` | tick |
| `wait_for_merge` | `min_interval, timeout` | tick |
| `ci_status` | `on_failure: { redirect_to, message_template }` | exit (script stages) |

Hooks return one of three verdicts: `Pass`, `Fail`, or `Redirect(target_stage)`. `Pass` lets the flow proceed; `Fail` triggers retry-or-fail; `Redirect` routes to the named stage with `reason: redirect`. `section_redirect` is the canonical example — used for review loops.

Hooks are a Go interface — adding one is ~20 lines + a test. The YAML uses tagged union form (`name: { args }`).

## Prompts

Two kinds, both plain markdown, both committed to git.

**Role prompts** (`.stagent/prompts/roles/<role>.md`) are sent ONCE as `--system-prompt` when a session is created for a `(task, role)`. They define identity, project context, conventions, tool preferences. Plain markdown, no templating (the role prompt is the same on every task).

**Stage prompts** (`.stagent/prompts/stages/<stage>.md`) are sent as the user message on EVERY entry to the stage — initial, retry, redirect, human_goto. They describe the immediate work: what to produce, what sections to fill, what prior artifacts to read, where to write output. Stage prompts ARE templated with task context:

- `{{.Task.ID}}`, `{{.Task.Title}}`, `{{.Task.Branch}}`, `{{.Task.WorktreeDir}}`
- `{{.ArtifactPath}}` — absolute path to this stage's artifact (`.stagent/tasks/<id>/<stage>.md`)
- `{{.PriorArtifacts}}` — list of `(stage_name, absolute_path)` for completed prior stages
- `{{.RedirectMessage}}` — present when this entry was triggered by a redirect or `goto -m`

Stage prompts remind the agent of the convention: the system judges completion via exit hooks; fill the artifact, satisfy the hooks (tests passing, sections complete, checkboxes ticked), exit.

## Templates

Artifact templates at `.stagent/templates/stages/<stage>.md` (committed to git). On stage entry, the `create_from_template` enter hook copies `templates/stages/<stage>.md` → `tasks/<id>/<stage>.md` (only if dest doesn't exist).

Templates are templated with the same task context as stage prompts.

Example `.stagent/templates/stages/define.md`:

```markdown
# Define: {{.Task.Title}}

## Problem

<!-- Describe the problem in 2-3 sentences. -->

## Approach

<!-- Outline the proposed approach in 50+ words. -->

## Completion

- [ ] Problem stated clearly
- [ ] Approach explained
- [ ] Edge cases considered
- [ ] Open questions surfaced
```

The matching stage hooks check this structure:

```yaml
exit:
  - file_exists: {}                                           # tasks/<id>/define.md
  - min_words: { section: Approach, min: 50 }
  - section_check: { section: Completion, expect: all_checked }
```

Notice the hooks don't specify `file:` — they default to `tasks/<id>/<stage>.md`, the stage's own artifact.
