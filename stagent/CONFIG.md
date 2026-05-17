# Config (`.stagent.yaml`)

Single file. Declares roles, stages, flows, hooks, and optional commands. Loaded once at daemon start and on `SIGHUP`.

## Full example

```yaml
project: my-project

# ─── Roles ────────────────────────────────────────────────────────────
# Who can do work. Maps to claude invocation params.
# v1: no containers. Agents run on the host in the task's git worktree.
roles:
  developer:
    model: opus
    skill: .stagent/skills/developer.md
    dangerous: true     # passes --dangerously-skip-permissions to claude -p
                        # required true for agent roles in v1 (headless mode)

  reviewer:
    model: sonnet
    skill: .stagent/skills/reviewer.md
    dangerous: true

# ─── Stages ───────────────────────────────────────────────────────────
# Three types: agent, human, script.
# max_runs is the total number of times a stage may be entered for a task
# (initial + retries + redirects + human_gotos). Defaults: 3 (agent/script), 1 (human).
stages:

  define:
    type: agent
    role: developer
    output: spec.md
    max_runs: 2
    hooks:
      enter:
        - create_from_template: { template: spec.md, dest: spec.md }
      exit:
        - file_exists: { path: spec.md }
        - min_words: { file: spec.md, section: Approach, min: 50 }
        - section_check: { file: spec.md, section: Completion, expect: all_checked }

  plan:
    type: agent
    role: developer
    output: plan.md
    max_runs: 2
    hooks:
      enter:
        - create_from_template: { template: plan.md, dest: plan.md }
      exit:
        - file_exists: { path: plan.md }
        - section_check: { file: plan.md, section: Completion, expect: all_checked }

  plan_review:
    type: human
    # human stages need no hooks; stagent approve is the signal

  code:
    type: agent
    role: developer
    output: code_notes.md
    max_runs: 7      # generous: review and CI both redirect back here
    hooks:
      enter:
        - run_shell: { cmd: "git rebase origin/main", fail_on_nonzero: false }
        - create_from_template: { template: code_notes.md, dest: code_notes.md }
      exit:
        - run_shell: { cmd: "go test ./...", fail_on_nonzero: true }
        - run_shell: { cmd: "go vet ./...",  fail_on_nonzero: true }
        - section_check: { file: code_notes.md, section: Completion, expect: all_checked }
        - run_shell: { cmd: "git push -u origin HEAD", fail_on_nonzero: true }

  review:
    type: agent
    role: reviewer
    output: review.md
    max_runs: 3      # cap how many times reviewer can reject before escalating
    hooks:
      enter:
        - create_from_template: { template: review.md, dest: review.md }
      exit:
        - file_exists: { path: review.md }
        - section_check: { file: review.md, section: Verdict, expect: all_checked }
        # If reviewer checked "Request changes", loop back to code with their notes.
        # Otherwise (Approve checked), flow proceeds to next stage.
        - section_redirect:
            file: review.md
            when_checked: "Request changes"
            redirect_to: code
            message_from_section: "Changes requested"   # body of this section becomes the redirect message

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

  quick:
    - define
    - code

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

- **Stage names are bare identifiers**, not dot paths. Sub-stage hierarchies from agenttree are gone — they added cognitive load without buying much. If you want grouping, prefix the names (`code_review`, `code_test`).
- **`type` is required** on every stage. One of `agent`, `human`, `script`.
- **`role` is required** on `agent` stages. Forbidden on `human` and `script`.
- **`output` is required** on `agent` stages. Forbidden on others.
- **`max_runs`** is the total times this stage may be entered across the task (any reason — initial, retry, redirect, human_goto). Defaults: 3 for `agent`/`script`, 1 for `human`.
- **`hooks.tick` is only valid** on `type: script` stages.
- **The agent never signals completion explicitly.** When its process exits (any reason), the daemon runs the exit hooks. Encode "is this done?" by writing exit hooks — typically `section_check` on a Completion section in the output artifact.
- **Hooks return one of three verdicts:** `Pass` (proceed), `Fail` (retry-or-fail), `Redirect(stage, message)` (route to chosen stage; loops happen this way).

## Hooks reference (v1)

| Hook | Args | When |
|---|---|---|
| `file_exists` | `path` | exit |
| `min_words` | `file, section, min` | exit |
| `section_check` | `file, section, expect: all_checked` | exit |
| `section_redirect` | `file, when_checked, redirect_to, message_from_section?` | exit |
| `create_from_template` | `template, dest` | enter |
| `run_shell` | `cmd, fail_on_nonzero, timeout` | enter / exit |
| `wait_for_ci` | `min_interval, timeout` | tick |
| `ci_status` | `on_failure: { redirect_to, message_template }` | exit (script stages) |
| `git_push` | `branch` | enter / exit |

Hooks return one of three verdicts: `Pass`, `Fail`, or `Redirect(target_stage)`. `Pass` lets the flow proceed; `Fail` triggers retry-or-fail; `Redirect` routes to the named stage with `reason: redirect`. `section_redirect` is the canonical example — used for review loops.

Hooks are a Go interface — adding one is ~20 lines + a test. The YAML uses tagged union form (`name: { args }`).

## Skills

Skills are plain markdown files passed to `claude -p` as the system prompt. They live at `.stagent/skills/<name>.md` and are committed to git. A stage's skill resolution:

1. `StageDef.Skill` if set
2. otherwise `Role.SkillFile`
3. otherwise a built-in default

Skills should remind the agent that the system judges completion via exit hooks — so the artifact must satisfy them (all checkboxes ticked, sections filled, tests passing) before the agent exits.

## Templates

Templates are markdown files at `.stagent/templates/<output_name>` (committed to git). They define the structure each stage's artifact starts with — section headings, checklists, prompts for the agent to answer.

On `stage.entered`, the `create_from_template` enter hook copies the template into `.stagent/tasks/<id>/<output_name>` (gitignored, lives in the main repo). The agent receives an absolute path to the artifact in its prompt and edits it directly.

Example `.stagent/templates/spec.md`:

```markdown
# Spec: {{.Task.Title}}

## Problem

<!-- Describe the problem in 2-3 sentences. -->

## Approach

<!-- Outline the proposed approach in 50+ words. -->

## Completion checklist

- [ ] Problem stated clearly
- [ ] Approach explained
- [ ] Edge cases considered
- [ ] Open questions surfaced
```

The corresponding stage hooks check the structure:

```yaml
exit:
  - file_exists: { path: spec.md }
  - min_words: { file: spec.md, section: Approach, min: 50 }
  - section_check: { file: spec.md, section: "Completion checklist", expect: all_checked }
```

Templates can use Go template syntax for task context (`{{.Task.Title}}`, `{{.Task.ID}}`, `{{.Task.Branch}}`). Skills do not — they're plain markdown, identical for every task.
