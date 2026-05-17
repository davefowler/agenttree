# Quickstart

Get a task running end-to-end in five minutes.

## Install

```bash
go install github.com/davefowler/stagent@latest
```

A Homebrew tap will follow once there's a v0.1 release. For now, `go install` gives you the `stagent` binary in your `$GOBIN`.

## Init a project

`stagent` is per-repo. From the root of the project you want to run tasks against:

```bash
cd my-project
stagent init
```

This writes:

```
.stagent.yaml                            # workflow config (committed)
.stagent/
  prompts/
    roles/{developer,reviewer}.md        # role system prompts (committed)
    stages/{code,review}.md              # stage user prompts (committed)
  templates/
    task.md                              # task file template (committed)
tasks/                                   # where task files live (committed)
.gitignore                               # appended with stagent runtime paths
```

`stagent init` also appends to `.gitignore`:

```
.stagent/stagent.db*
.stagent/runner.pid
.worktrees/
```

Commit everything except those. Your team should see your config, prompts, and task files; the SQLite log and runtime artifacts are per-developer.

## Create a task

Two ways. Pick whichever fits your workflow.

### A. Write the spec first, register it

Plan in your editor of choice. Create `tasks/fix-login.md` (any filename works) with the [task file shape](configuration/task-files.md):

```markdown
# Fix login redirect bug

## Problem
The /login redirect drops the `?next=` query param when the user is already
authenticated, so they land on /dashboard instead of the page they came from.

## Context
The redirect logic is in `web/auth/middleware.go`. We touched this in #142
but didn't cover the already-authenticated path.

## Possible solutions
1. Preserve the full URL through the auth check, not just the path.
2. Always re-issue `?next=` on the redirect to /dashboard.

Option 1 is cleaner.

## Implementation plan
- [ ] Read web/auth/middleware.go and identify the early-return path
- [ ] Preserve the `?next=` param through the redirect
- [ ] Add a test in web/auth/middleware_test.go for the already-auth case
- [ ] Run the full auth test suite
```

Then register it:

```bash
stagent new tasks/fix-login.md
```

`stagent new` assigns the next task ID, renames the file to `tasks/001-fix-login.md`, and appends a `task.created` event.

### B. Start from the template

```bash
stagent new "Fix login redirect bug"
```

This creates `tasks/001-fix-login-redirect-bug.md` from `.stagent/templates/task.md` and emits `task.created`. Fill in the sections in your editor.

Either path produces the same result: a task file at `tasks/<id>-<slug>.md` and a single event in the log. No worktree, no branch, no Claude session yet.

## Start the runner

```bash
stagent run
```

The runner ticks every 2 seconds (configurable in `.stagent.yaml`). On the first tick after `task.created`, it picks up your task and enters the first stage of the default flow:

```
setup → code → pr → review → human_review → cleanup
```

- **`setup`** creates `.worktrees/task-001/` on branch `task-001` off `origin/main`, runs any install hooks you've configured.
- **`code`** spawns a Claude session as the `developer` role and points it at the task file. The developer reads "Implementation plan," writes code, runs tests, ticks boxes, exits.
- **`pr`** pushes the branch and opens a PR via `gh`, then polls CI.
- **`review`** spawns a `reviewer` Claude session that reads the diff and appends `### Pass N` under `## Reviews`. If any box (other than nits) is unticked, the runner redirects to `code` with the reviewer's notes.
- **`human_review`** pauses for `stagent approve <id>` or a detected PR merge.
- **`cleanup`** removes the worktree and branch.

The runner blocks the terminal. `Ctrl-C` to stop; restart with `stagent run` and it picks up where it left off.

## Observe progress

In another terminal:

```bash
stagent status                  # all tasks, current stage, status
stagent show 1                  # detail for task 1
stagent log 1                   # event log for task 1 (tails)
```

The committed task file shows the actual work — read `tasks/001-fix-login-redirect-bug.md` to see what the developer wrote and what the reviewer said.

## Approve and ship

When `human_review` is reached, the runner pauses. Read the diff, check the PR. To advance:

```bash
stagent approve 1
```

Or just merge the PR in GitHub — the `wait_for_merge` tick hook detects it and completes the stage on its own. Either path triggers `cleanup`, which removes the worktree and emits `task.completed`.

## What to read next

- **[Concepts → Stages, flows, hooks](concepts/stages-flows-hooks.md)** — what each stage type does, how hooks work, how redirects loop back.
- **[Configuration → The `.stagent.yaml` file](configuration/stagent-yaml.md)** — every field with examples.
- **[Patterns → Review loop](patterns/review-loop.md)** — full worked example of the code↔review loop.
- **[Reference → CLI](reference/cli.md)** — every command.
