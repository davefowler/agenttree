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
# Three types: agent, human, heartbeat.
stages:

  define:
    type: agent
    role: developer
    output: spec.md
    retries: 1
    hooks:
      enter:
        - create_from_template: { template: spec.md.tmpl }
      exit:
        - file_exists: { path: spec.md }
        - min_words: { file: spec.md, section: Approach, min: 50 }
        - section_check: { file: spec.md, section: Completion, expect: all_checked }

  plan:
    type: agent
    role: developer
    output: plan.md
    retries: 1
    hooks:
      exit:
        - file_exists: { path: plan.md }
        - section_check: { file: plan.md, section: Completion, expect: all_checked }

  plan_review:
    type: human
    hooks:
      exit: []      # nothing — human.approved is the signal

  code:
    type: agent
    role: developer
    output: code_notes.md
    retries: 2
    hooks:
      exit:
        - run_shell: { cmd: "go test ./...", fail_on_nonzero: true }
        - run_shell: { cmd: "go vet ./...",  fail_on_nonzero: true }
        - section_check: { file: code_notes.md, section: Completion, expect: all_checked }

  independent_review:
    type: agent
    role: reviewer
    output: review.md
    retries: 0
    hooks:
      exit:
        - section_check: { file: review.md, section: Verdict, expect: all_checked }

  ci_wait:
    type: heartbeat
    hooks:
      heartbeat:
        - wait_for_ci: { min_interval: 30s, timeout: 30m }
      exit:
        - ci_passed: {}

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
    - independent_review
    - ci_wait
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

- **Stage names are bare identifiers**, not dot paths. Sub-stage hierarchies from agenttree are gone — they were rarely load-bearing and added cognitive load. If you want grouping, name stages with a prefix (`code_review`, `code_test`).
- **`type` is required** on every stage. One of `agent`, `human`, `heartbeat`.
- **`role` is required** on `agent` stages. Forbidden on `human` and `heartbeat`.
- **`output` is required** on `agent` stages. Forbidden on others.
- **`retries` defaults to 0**. Means 1 attempt total. `retries: 2` means up to 3 attempts.
- **`hooks.heartbeat` is only valid** on `type: heartbeat` stages.
- **The agent never signals completion explicitly.** When its process exits (any reason), the heartbeat runs the exit hooks. Encode "is this done?" by writing exit hooks — typically `section_check` on a Completion section in the output artifact.

## Hooks reference (v1)

| Hook | Args | When |
|---|---|---|
| `file_exists` | `path` | exit |
| `min_words` | `file, section, min` | exit |
| `section_check` | `file, section, expect: all_checked` | exit |
| `create_from_template` | `template, dest` | enter |
| `run_shell` | `cmd, fail_on_nonzero, timeout` | enter / exit |
| `wait_for_ci` | `min_interval, timeout` | heartbeat |
| `ci_passed` | — | exit (heartbeat stages) |
| `git_push` | `branch` | enter / exit / heartbeat |
| `ensure_pr` | `base, title_from` | exit / heartbeat |

Hooks are a Go interface — adding one is ~20 lines + a test. The YAML uses tagged union form (`name: { args }`).

## Skills

Skills are markdown files passed to `claude -p` as the system prompt. They live at `.stagent/skills/<name>.md` and are committed to git. A stage's skill resolution:

1. `StageDef.Skill` if set
2. otherwise `Role.SkillFile`
3. otherwise a built-in default

Skills should remind the agent that the system judges completion via exit hooks — so the artifact must satisfy them (e.g. all checkboxes ticked, tests passing) before the agent exits.
