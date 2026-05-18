# Config (`.stagent.yaml`)

Single file. Declares roles, stages, flows, hooks, and optional commands. Loaded once at runner start and on `SIGHUP`.

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

  setup:
    type: script
    max_runs: 3
    hooks:
      enter:
        # Standard worktree + branch creation. Override the cmd if your project
        # uses a different path convention or base branch.
        - run_shell:
            cmd: "git worktree add {{.Task.WorktreeDir}} -b {{.Task.Branch}} origin/main"
            fail_on_nonzero: true

        # Project-specific install / fixture setup goes here. Examples:
        # - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && go mod download" }
        # - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && npm ci" }
        # - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && cp .env.example .env" }

  code:
    type: agent
    role: developer
    max_runs: 7    # generous: pr, review, and human_review can all redirect back
    hooks:
      enter:
        # Rebase on every code entry — on review/CI redirects, main may have moved.
        # fail_on_nonzero: true so merge conflicts escalate instead of silently
        # producing broken code.
        - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && git rebase origin/main", fail_on_nonzero: true }
      exit:
        - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && go test ./...", fail_on_nonzero: true }
        - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && go vet ./...",  fail_on_nonzero: true }
        # Implementation plan is human-written; agent checks items off as work completes.
        - section_check: { section: "Implementation plan", expect: all_checked }
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
        # Reviewer appends a new "### Pass N" subsection under "## Reviews"
        # on every entry. The regex in the last segment matches every Pass;
        # the hook picks the LAST in document order by default. If any box
        # is unticked, the whole Pass section becomes the redirect message
        # back to code.
        - section_check:
            section: "Reviews > /^Pass \\d+$/[-1]"
            expect: all_checked
            on_fail:
              redirect_to: code
              message_from_section: "Reviews > /^Pass \\d+$/[-1]"

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
    - setup          # create worktree, branch, install deps
    - code           # implement based on the user-written task file
    - pr             # push + open PR + wait for CI green
    - review         # agent reviewer; redirects to code if changes requested
    - human_review   # completes via `stagent approve` OR PR merge; polls CI throughout
    - cleanup        # remove worktree, delete branch

  quick:
    - setup
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
  interval: 2s          # how often the runner ticks
```

## Schema rules

- **Stage names are bare identifiers** and key the prompt path (`prompts/stages/<name>.md`). They do NOT key per-stage files in the task dir — there's one task file per task, shared by all stages.
- **One task file per task** at `<tasks_dir>/<id>-<slug>.md` (committed to git). Sections within it represent stages. Hooks reference section paths.
- **`type` is required** on every stage. One of `agent`, `human`, `script`.
- **`role` is required** on `agent` stages. Forbidden on `human` and `script`.
- **No `output:`, `skill:`, `template:`, or per-stage path overrides.** Everything is by convention or by section reference.
- **`max_runs`** is the total times this stage may be entered across the task (any reason — initial, retry, redirect, human_goto). Defaults: 3 for `agent`/`script`, 1 for `human`.
- **`hooks.tick` is valid** on `type: script` AND `type: human` stages. Not on `agent` stages — agents own their own turn. On human stages, tick hooks run while waiting (use `min_interval` to avoid hot-polling).
- **The agent never signals completion explicitly.** When its process exits (any reason), the runner runs exit hooks. Encode "is this done?" by writing exit hooks — typically `section_check` on a `Completion` subsection inside the stage's section in the task file.
- **Hooks return one of four verdicts:** `Pass` (satisfied; complete if others agree), `NotYet` (tick hooks only; keep waiting), `Fail` (retry-or-fail), `Redirect(stage, message)` (route to chosen stage; loops happen this way).
- **A stage with tick hooks completes** when all tick hooks return `Pass` on the same tick AND exit hooks then pass.
- **Human stages complete** via EITHER `stagent approve <task>` OR all tick hooks returning `Pass`. Whichever fires first.

## Hooks reference (v1)

| Hook | Args | When |
|---|---|---|
All hooks that reference sections operate on the task file at `{{.TaskFile}}` unless `file:` is overridden. Section paths use `>` as separator: `"Code > Notes"` resolves to the `### Notes` h3 under the `## Code` h2. Top-level sections (h2) use just the section name: `"Implementation plan"`.

**Checkbox parsing:** `- [ ]` is unchecked. `- [x]` and `- [X]` are both checked (case-insensitive). HTML comments (`<!-- ... -->`) inside a section are ignored when checking.

| Hook | Args | When |
|---|---|---|
| `min_words` | `section, min, file?` | exit |
| `section_check` | `section, expect: all_checked, file?, on_fail?: { redirect_to, message_from_section }` | exit |
| `section_redirect` | `when_checked, redirect_to, message_from_section?, section?, file?` | exit |
| `run_shell` | `cmd, fail_on_nonzero, timeout` | enter / exit |
| `wait_for_ci` | `min_interval, timeout` | tick |
| `wait_for_merge` | `min_interval, timeout` | tick |
| `ci_status` | `min_interval?, on_failure: { redirect_to, message_template }` | exit (script) / tick (human) |

**On `section_check.on_fail`:** by default, a failed `section_check` follows the normal retry path (retry the stage if budget allows, else `stage.failed`). When `on_fail` is provided, the hook instead returns `Redirect(target_stage, message)` — the message body is the text content of `message_from_section`. This is the canonical pattern for "if reviewer didn't approve, send back to developer with notes" — no special hook needed.

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

Single file at `.stagent/templates/task.md` (committed). Used by `stagent new "<title>"` (no file argument) to seed a fresh task file at `<tasks_dir>/<id>-<slug>.md`. Users who write their own specs in Cursor or elsewhere and run `stagent new <path>` never see it.

Templated with `{{.Task.Title}}`, `{{.Task.ID}}`, etc.

The default template structure (matches the default flow's hooks):

```markdown
# {{.Task.Title}}

## Problem
<!-- 2-3 sentences. -->

## Context
<!-- Background the agent won't infer: where code lives, prior attempts, constraints, links. -->

## Possible solutions
<!-- 1-3 approaches you've considered. Shapes how the agent thinks. -->

## Implementation plan
<!-- Granular checklist; code stage's section_check requires all checked. -->
- [ ] (Replace with the first concrete task)
- [ ] (Add more granular items as needed)

## Reviews
<!--
Reviewer appends "### Pass N" on each entry. The section_check hook keys
on `Reviews > /^Pass \d+$/` (latest pass — regex match, pick last). "Review approved" is always the
LAST checkbox; it means no critical/high/medium issues remain. Low-
severity nits do not block approval. Lint and type errors are CI's job.
-->

## Code
<!-- Filled by the developer agent. -->
### Notes
<!-- Implementation notes. -->
```

See [`scaffold/.stagent/templates/task.md`](../scaffold/.stagent/templates/task.md) for the version `stagent init` actually emits (with explanatory comments in every section and the severity rubric inline).

If you change the section headings, update the corresponding hook `section:` references in `.stagent.yaml`.

### The Pass-N review pattern

Each entry to the `review` stage appends a new `### Pass N` subsection under `## Reviews`. The reviewer never overwrites prior passes; the file keeps the full audit trail.

```markdown
## Reviews

### Pass 1
- [ ] Tests cover the new behavior on the primary path
- [x] Public API changes are documented
- [ ] Review approved

The retry logic in client.go:142 swallows network errors silently —
return them so callers can decide. **Severity: high.** Also no test
for the auth-expired path. **Severity: medium.**

### Pass 2
- [x] Tests cover the new behavior on the primary path
- [x] Public API changes are documented
- [x] Review approved

LGTM. Network errors now propagate; auth-expired path covered.
```

The hook syntax `"Reviews > /^Pass \\d+$/[-1]"` resolves to the H3 subsection whose name matches `Pass N` with the highest integer N. The same syntax in `message_from_section` returns the full text of that subsection (checkboxes + notes) as the redirect message — so the developer sees exactly which boxes were unticked and the reviewer's reasoning.

**Why a new section each pass instead of clearing in place:**

- The append-only design tenet applies to documents as well as events. Editing prior verdicts is a destructive operation; appending is not.
- Re-reviewers can see what prior passes raised and verify each item was addressed. Hiding history makes them re-discover everything.
- The committed task file in `git log` shows the workflow's full progression — useful in PR archaeology.

**Should the new reviewer see the old reviews?** Yes. Continuity is real value, and anchoring risk is manageable via the stage prompt ("verify whether each prior concern was addressed; raise new issues only if you see them in the latest diff"). Session boundness (`bound: stage` vs `bound: task`) controls Claude's *memory*, not the reviewer's *visibility* into the task file.
