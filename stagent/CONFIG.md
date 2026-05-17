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
    bound: task         # one session per (task, role) — continues across loops

  reviewer:
    model: sonnet
    dangerous: true
    bound: stage        # fresh eyes each time the reviewer enters the stage

# ─── Tasks ────────────────────────────────────────────────────────────
# Where task files live. One file per task. Sections within the file
# represent stages. Hooks reference section paths like "Code > Completion".
tasks_dir: tasks      # default; configurable

# ─── Stages ───────────────────────────────────────────────────────────
# Three types: agent, human, script.
#
# Conventions (no per-stage path overrides in YAML):
#   - task file:      <tasks_dir>/<id>-<slug>.md  (one per task, all stages share it)
#   - stage prompt:   .stagent/prompts/stages/<stage>.md
#   - role prompt:    .stagent/prompts/roles/<role>.md
#
# Hooks check sections within the task file via paths like "Code > Completion".
# max_runs is the total entries to a stage across the task's lifetime
# (initial + retries + redirects + human_gotos). Defaults: 3 (agent/script), 1 (human).
#
# stagent is for the EXECUTION loop only. Planning (problem, approach) happens
# elsewhere — the user provides a complete task file before starting.
stages:

  code:
    type: agent
    role: developer
    max_runs: 7    # generous: pr, review, and human_review can all redirect back
    hooks:
      enter:
        - run_shell: { cmd: "git rebase origin/main", fail_on_nonzero: false }
      exit:
        - run_shell: { cmd: "go test ./...", fail_on_nonzero: true }
        - run_shell: { cmd: "go vet ./...",  fail_on_nonzero: true }
        - section_check: { section: "Code > Completion", expect: all_checked }
    # NOTE: code does NOT push or open PRs. The pr stage handles all gh interaction.

  pr:
    type: script
    max_runs: 5
    hooks:
      enter:
        - run_shell: { cmd: "git push -u origin HEAD" }
        - run_shell: { cmd: "gh pr create --fill || true", fail_on_nonzero: false }
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
        - section_check: { section: "Review > Verdict", expect: all_checked }
        - section_redirect:
            section_verdict: "Review > Verdict"
            when_checked: "Request changes"
            redirect_to: code
            message_from_section: "Review > Changes requested"

  human_review:
    type: human
    # Two parallel completion paths:
    #   1. `stagent approve <task>` — human approves explicitly
    #   2. wait_for_merge tick hook detects the PR was merged in GH
    # Whichever fires first satisfies the stage.
    hooks:
      tick:
        - wait_for_merge: { min_interval: 1m, timeout: 24h }   # Pass once merged
        - ci_status:                                            # also guard against CI going red mid-review
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
        - run_shell: { cmd: "git branch -D {{.Task.Branch}} 2>/dev/null || true", fail_on_nonzero: false }

# ─── Flows ────────────────────────────────────────────────────────────
# Ordered lists of stage names. A task picks one at creation time.
flows:
  default:
    - code           # implement based on the user-written task file
    - pr             # push + open PR + wait for CI green
    - review         # agent reviewer; redirects to code if changes requested
    - human_review   # completes via `stagent approve` OR PR merge; polls CI throughout
    - cleanup        # remove worktree, delete branch

  quick:
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

- **Stage names are bare identifiers** and key the prompt path (`prompts/stages/<name>.md`). They do NOT key per-stage files in the task dir — there's one task file per task, shared by all stages.
- **One task file per task** at `<tasks_dir>/<id>-<slug>.md` (committed to git). Sections within it represent stages. Hooks reference section paths.
- **`type` is required** on every stage. One of `agent`, `human`, `script`.
- **`role` is required** on `agent` stages. Forbidden on `human` and `script`.
- **No `output:`, `skill:`, `template:`, or per-stage path overrides.** Everything is by convention or by section reference.
- **`max_runs`** is the total times this stage may be entered across the task (any reason — initial, retry, redirect, human_goto). Defaults: 3 for `agent`/`script`, 1 for `human`.
- **`hooks.tick` is valid** on `type: script` AND `type: human` stages. Not on `agent` stages — agents own their own turn. On human stages, tick hooks run while waiting (use `min_interval` to avoid hot-polling).
- **The agent never signals completion explicitly.** When its process exits (any reason), the daemon runs exit hooks. Encode "is this done?" by writing exit hooks — typically `section_check` on a `Completion` subsection inside the stage's section in the task file.
- **Hooks return one of four verdicts:** `Pass` (satisfied; complete if others agree), `NotYet` (tick hooks only; keep waiting), `Fail` (retry-or-fail), `Redirect(stage, message)` (route to chosen stage; loops happen this way).
- **A stage with tick hooks completes** when all tick hooks return `Pass` on the same tick AND exit hooks then pass.
- **Human stages complete** via EITHER `stagent approve <task>` OR all tick hooks returning `Pass`. Whichever fires first.

## Hooks reference (v1)

| Hook | Args | When |
|---|---|---|
All hooks that reference sections operate on the task file at `{{.TaskFile}}` unless `file:` is overridden. Section paths use `>` as separator: `"Code > Completion"` resolves to the `### Completion` h3 under the `## Code` h2.

| Hook | Args | When |
|---|---|---|
| `min_words` | `section, min, file?` | exit |
| `section_check` | `section, expect: all_checked, file?` | exit |
| `section_redirect` | `section_verdict, when_checked, redirect_to, message_from_section?, file?` | exit |
| `run_shell` | `cmd, fail_on_nonzero, timeout` | enter / exit |
| `wait_for_ci` | `min_interval, timeout` | tick |
| `wait_for_merge` | `min_interval, timeout` | tick |
| `ci_status` | `min_interval?, on_failure: { redirect_to, message_template }` | exit (script) / tick (human) |

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

## Task template

Optional, single file at `.stagent/templates/task.md`. Used only by `stagent task new "<title>"` (no file argument) — copied to `<tasks_dir>/<id>-<slug>.md`. Users who write their own task files in Cursor or elsewhere never see it.

Templated with `{{.Task.Title}}`, `{{.Task.ID}}`, etc.

Example `.stagent/templates/task.md`:

```markdown
# {{.Task.Title}}

## Problem
<!-- Why we're doing this. -->

## Approach
<!-- High-level plan. Fill in before starting stagent. -->

## Code
<!-- The developer agent fills this. -->
### Notes
<!-- What was implemented and why. -->
### Completion
- [ ] Implementation matches the Approach
- [ ] Tests pass locally
- [ ] No new lint warnings

## Review
<!-- The reviewer agent fills this. -->
### Verdict
- [ ] Approve
- [ ] Request changes
### Changes requested
<!-- If "Request changes" is checked, this section is the redirect message. -->
```

Section structure matches the hooks in the default flow. If you change the headings, update the hooks' `section:` references to match.
