# Pattern: the review loop

A full worked example of the `code ↔ review` redirect loop — what's in the YAML, what's in the task file, what each agent sees, what happens at each transition.

## The shape

```
┌──────┐      pass        ┌────────┐      pass        ┌──────────────┐
│ code │ ───────────────▶ │ review │ ───────────────▶ │ next stage…  │
└──────┘                  └────────┘                  └──────────────┘
   ▲                          │
   │   redirect (latest Pass) │
   └──────────────────────────┘
```

Each entry to `review` appends a new `### Pass N` subsection in the task file. The exit hook checks the latest pass. If any box is unticked, the runner redirects to `code` with the pass body as the message.

## The YAML

```yaml
stages:
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

flows:
  default:
    - setup
    - code
    - pr
    - review
    - human_review
    - cleanup
```

Key choices:

- **`code.max_runs: 7`** — generous. CI, the agent reviewer, and the human reviewer can each redirect back. 7 covers a worst-case 3-round agent review loop plus a couple of CI rounds.
- **`review.max_runs: 3`** — strict. If the reviewer rejects three times, the task fails for human attention. (Tweak based on how nitpicky your reviewer prompt is.)
- **`developer` is `bound: task`** — the developer's Claude session continues across all `code` entries. On round 2, it remembers what it did on round 1.
- **`reviewer` is `bound: stage`** — each review pass uses a fresh Claude session. The reviewer reads prior passes from the task file (which lives on disk) but doesn't carry session memory between passes.

## The task file (initial state)

```markdown
# Fix login redirect bug

## Problem
The /login redirect drops the `?next=` query param when the user is
already authenticated, so they land on /dashboard instead of where they
came from.

## Context
Redirect logic is in `web/auth/middleware.go`. We touched this in #142
but didn't cover the already-authenticated path.

## Possible solutions
1. Preserve the full URL through the auth check.
2. Always re-issue `?next=` on the redirect.

Option 1 is cleaner.

## Implementation plan
- [ ] Read web/auth/middleware.go and identify the early-return path
- [ ] Preserve the `?next=` param through the redirect
- [ ] Add a test for the already-auth case
- [ ] Run the full auth test suite

## Reviews

## Code
### Notes
```

## Round 1 — developer

The runner spawns Claude as `developer`. Stage prompt (rendered):

```
Implement the work described in this task.

- Task file: /abs/.worktrees/task-001/tasks/001-fix-login.md
- Worktree: /abs/.worktrees/task-001
- Branch: task-001

Steps:
1. Read the entire task file. ...
(...)
```

The developer reads the task file, opens `web/auth/middleware.go`, writes the fix, adds a test, runs the suite. As it goes, it edits the task file:

```markdown
## Implementation plan
- [x] Read web/auth/middleware.go and identify the early-return path
- [x] Preserve the `?next=` param through the redirect
- [x] Add a test for the already-auth case
- [x] Run the full auth test suite

(...)

## Code
### Notes
Found the early-return at middleware.go:78. The redirect was
building the target URL from `r.URL.Path` alone, dropping query
params. Switched to `r.URL.RequestURI()` to preserve them.
Added TestAuthMiddleware_AlreadyAuthed_PreservesNext.
```

It exits.

Exit hooks fire:

1. `go test ./...` → pass.
2. `go vet ./...` → pass.
3. `section_check { section: "Implementation plan", expect: all_checked }` → pass.

`stage.completed` for `code`. Flow advances to `pr`, which pushes the branch and opens a PR. CI runs, comes back green. Flow advances to `review`.

## Round 1 — reviewer

The runner spawns Claude as `reviewer`. Fresh session (`bound: stage`).

Stage prompt:

```
Review the developer's work on this task.

- Task file: /abs/.worktrees/task-001/tasks/001-fix-login.md
- Worktree: /abs/.worktrees/task-001
- Branch: task-001

Steps:
1. Read the entire task file. Note the Implementation plan, prior Pass
   sections (if any), and the developer's Code > Notes.
2. Inspect the diff: git -C /abs/.worktrees/task-001 diff origin/main...HEAD
3. ...
```

The reviewer reads the file, runs the diff, evaluates. It finds:

- The fix is correct on the primary path.
- The test covers the case but doesn't verify the `?next=` param actually round-trips through the redirect.
- No security issues.

It writes Pass 1:

```markdown
## Reviews

### Pass 1
- [ ] Review approved

The test `TestAuthMiddleware_AlreadyAuthed_PreservesNext` checks the
HTTP status code but doesn't assert the redirect target's query
string includes `?next=`. **Severity: medium** — without that
assertion, a future refactor could re-introduce the bug without
turning the test red.

Add a check like:
    assert.Equal(t, "/protected?next=/profile", w.Header().Get("Location"))
```

It exits.

Exit hook fires:

`section_check { section: "Reviews > /^Pass \\d+$/[-1]" }` → finds Pass 1, sees `- [ ] Review approved` unchecked, returns `Redirect(code, <body of Pass 1>)`.

Two events appended:

1. `stage.completed` for `review` (Pass 1 was written — the work was done).
2. `stage.entered` for `code` with `reason: redirect`, `from_stage: review`.

## Round 2 — developer (redirect)

The developer's session is resumed (`claude --resume <uuid>` — same UUID as round 1). The stage prompt is sent with `{{.RedirectMessage}}` filled in:

```
Implement the work described in this task.
(... standard instructions ...)

## Prior context

### Pass 1
- [ ] Review approved

The test `TestAuthMiddleware_AlreadyAuthed_PreservesNext` checks the
HTTP status code but doesn't assert the redirect target's query
string includes `?next=`. **Severity: medium** — without that
assertion, a future refactor could re-introduce the bug without
turning the test red.

Add a check like:
    assert.Equal(t, "/protected?next=/profile", w.Header().Get("Location"))
```

The developer's session memory has everything from round 1 — what it implemented, why it picked option 1, the file it edited. The "Prior context" block tells it what to do this round.

It updates the test, runs it, edits the task file's `## Code > Notes` to append:

```markdown
### Notes
(...prior content...)

**Round 2:** Added Location header assertion to
TestAuthMiddleware_AlreadyAuthed_PreservesNext as requested.
```

It exits.

Exit hooks fire (tests pass, vet passes, Implementation plan still all checked). `stage.completed` for `code`. Flow advances to `pr` again — the same PR is updated by the new push (`git push -u origin HEAD`). CI runs, green. Flow advances to `review`.

## Round 2 — reviewer

Fresh session (`bound: stage`). Reads the task file — sees Pass 1, sees the developer's Round 2 notes, sees the new diff (`git diff origin/main...HEAD` now shows two commits). The reviewer prompt instructs:

> On a re-review (Pass 2+), verify that prior pass's concerns were actually addressed.

It checks: yes, the Location assertion is there. No new issues. Writes Pass 2:

```markdown
### Pass 2
- [x] Review approved

LGTM. Prior pass's medium-severity issue is addressed —
TestAuthMiddleware_AlreadyAuthed_PreservesNext now asserts
the redirect Location includes the `?next=` param.
```

Exits.

Exit hook: `section_check { section: "Reviews > /^Pass \\d+$/[-1]" }` → finds Pass 2, all boxes checked → `Pass`.

`stage.completed` for `review`. Flow advances to `human_review`.

## The committed audit trail

After the task ships, the task file in git looks like:

```markdown
# Fix login redirect bug
(... problem, context, solutions, implementation plan all-checked ...)

## Reviews

### Pass 1
- [ ] Review approved

The test ... checks the HTTP status code but doesn't assert the redirect
target's query string includes `?next=`. **Severity: medium** ...

### Pass 2
- [x] Review approved

LGTM. Prior pass's medium-severity issue is addressed ...

## Code
### Notes
Found the early-return at middleware.go:78 ...

**Round 2:** Added Location header assertion ...
```

Six weeks later, someone reading the PR can see the whole back-and-forth. The reviewer pushed back on a test assertion; the developer added it; the reviewer approved. That history is preserved in the committed file — not in chat, not in a CI log, not in a vanished tmp file.

## What you'd change

If your project wants more (or different) checks:

- **Stricter review:** add boxes to the preloaded Pass template in `.stagent/templates/task.md`:
  ```markdown
  ### Pass 1
  - [ ] Tests cover the new behavior
  - [ ] Public API changes are documented
  - [ ] Performance impact is acceptable on the hot path
  - [ ] Review approved
  ```
  These propagate to every new task. The reviewer copies the box list into each new Pass.

- **Looser review:** drop the `section_check` entirely and let `human_review` be the only gate.

- **CI as part of review:** add a `wait_for_ci` tick hook on `review` so the reviewer can't approve while CI is red. (Be careful: combined with the `pr` stage's `wait_for_ci`, this can deadlock if CI flakes — pick one.)

- **Multiple reviewers:** define a `review_security` stage with a `security_reviewer` role; chain `review → review_security` in the flow. Each stage gets its own Pass section in the task file (`## Reviews` and `## Security reviews` say).

## Why this works

The pattern relies on a few invariants:

- **The reviewer always sees prior passes** because the task file is on disk and the prompt explicitly tells it to read them.
- **The redirect message is rich enough** to act on — it's the whole Pass section, not a one-line "rejected."
- **The developer's session continues** across rounds (`bound: task`), so it doesn't re-research the codebase each time.
- **`max_runs` caps the loop** so a pathological reviewer or developer can't burn unbounded budget.
- **Everything is committed** — the audit trail survives runner restarts, daemon crashes, machine reboots.
