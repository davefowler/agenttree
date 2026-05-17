# Decisions

Locked design decisions that the implementation can proceed from. Items in **Locked** are the contract. Items in **Tabled** are intentionally deferred — capture the thinking, defer the work.

This doc supersedes the inline rationale in earlier `notes/*.md` files when they conflict.

---

## Locked

### 1. Section-path grammar (for hooks)

Hooks reference sections in the task file via a path of `>`-separated segments:

```
"H2-name > H3-name > ..."
```

**Segments are one of two forms:**

- **Literal**: exact heading text. Whitespace inside the name is collapsed (matching `"Review  Plan"` against `## Review Plan`). Case-sensitive.
- **Regex**: wrapped in `/…/`. Matches H<parent+1> children whose visible heading text matches the pattern. Go regex syntax (`regexp` package, RE2).

**Examples:**

```yaml
section: "Implementation plan"            # literal H2
section: "Code > Notes"                   # literal H2 > literal H3
section: "Reviews > /^Pass \\d+$/"        # literal H2 > regex H3
```

**Matching rules:**

- **Literal segments must match exactly one section.** Zero matches → `Fail("section not found")`. Multiple matches → `Fail("ambiguous section path")`. Duplicate headings under the same parent are a task-file authoring error and the validator catches them up front.
- **Regex segments may match zero, one, or many.** When the regex matches multiple, the hook picks **the last in document order** by default. (Append-only files mean "last in document order" = "most recently appended.")
- **`pick:` modifier** overrides selection when a regex matches multiple. Values: `last` (default), `first`. We do not support `all` in v0.1 — if you need fan-out, write multiple hooks.
- **Regex segments may not contain `>`** (which is the segment separator). Use character classes (`[>]`) if you genuinely need it. In practice heading text won't.
- **Regex flags**: no `/.../i` suffix. Use inline `(?i)` per RE2.

**Why regex over the original `[-1]` proposal:** less bespoke syntax to teach, no new mental model, generalizes (regex can express `"Pass 3 and later"` if we ever care), and standard tools (grep, jq, etc.) already use the convention.

### 2. `section_check` on a section with zero checkboxes → `Fail`

```yaml
- section_check:
    section: "Reviews > /^Pass \\d+$/"
    expect: all_checked
```

If the matched section contains zero list items, the hook returns:

```
Fail("section '<resolved path>' has no checkboxes; likely a typo or missing required content")
```

Not "vacuously satisfied." An empty checklist almost always means the agent didn't write what it was supposed to write.

### 3. Task validator — `validate_task_sections` hook

A single new hook validates that the task file has every section the configured hooks need, with the right shape.

**Behavior:**

The hook walks the loaded config, identifies every `section:` reference reachable from the task's flow, and verifies:

| Reference shape | Validator requires |
|---|---|
| Literal exact path | Section exists. |
| Regex path | Parent segment exists. Zero matches on the regex itself is allowed (e.g. `Reviews > /^Pass \d+$/` matches nothing on initial task creation, by design). |
| `section_check { expect: all_checked }` with literal path | Section exists AND contains ≥1 checkbox. |
| `section_check` with regex path | Parent exists; checkbox check happens at runtime against the matched section. |
| `min_words` | Section exists. |
| `message_from_section` | Section exists (if literal) or parent exists (if regex). |

It also checks structural well-formedness:

- The task file has exactly one H1 (the title).
- No H<n+2> heading appears without its H<n+1> parent (no `### Foo` directly under H1).
- Heading text is unique within its parent. Two `### Notes` under the same H2 is an authoring error.

**Two callsites, one implementation:**

1. **At `stagent new`** — the CLI calls the validator before appending `task.created`. If it fails, print the error and exit non-zero; nothing is recorded in the event log.
2. **As an `enter` hook on `setup`** — defense in depth. Catches edits to the task file between `new` and `run`, or hook additions from a hot-reloaded config. Failure here is a normal `stage.failed`; retryable via `stagent goto <task> setup` after the user fixes the file.

The default `setup` stage in the scaffold includes the hook:

```yaml
setup:
  type: script
  hooks:
    enter:
      - validate_task_sections: {}
      - run_shell: { cmd: "git worktree add ...", fail_on_nonzero: true }
```

### 4. Reviewer model default: `sonnet`

Cost matters when reviews trigger on every `code` redirect. The reviewer prompt is now substantive enough (the post-`98c2d40` rewrite) that sonnet handles it well. Users who want opus flip one line.

### 5. Tests use a mock `claude` binary

Ship a `stagent-fakeclaude` binary as part of the test harness. The runner accepts a `--claude-bin <path>` flag (and honors `$STAGENT_CLAUDE_BIN`); tests point it at the mock.

**The mock honors the same flags as real Claude:**

- `-p "<prompt>"` — headless invocation; reads the prompt, picks a response, writes a transcript line, exits.
- `--session-id <uuid>` — uses the supplied UUID, writes the JSONL to `~/.claude/projects/<encoded-cwd>/<uuid>.jsonl`.
- `--resume <uuid>` — appends to the existing JSONL.
- `--system-prompt <text-or-@file>` — accepted; recorded in the transcript so tests can assert it was passed correctly.
- `--dangerously-skip-permissions` — accepted as a no-op (the mock doesn't enforce permissions anyway).

**Response source.** The mock reads responses from a scripted file pointed at by `$STAGENT_FAKE_RESPONSES`. Two supported shapes:

- A **queue** (JSON array): each agent invocation pops the next entry. Simple, deterministic, order-dependent.
- A **prompt-prefix map** (JSON object): `{prompt_prefix_substring → response}`. The mock matches the incoming prompt against keys (first match wins) and uses the response. Less brittle when ordering changes.

A response entry can specify a custom exit code, a delay before exiting (to simulate slow agents), and whether the mock should write the agent's "output" by editing files (the mock follows scripted file ops so tests can assert hook behavior against realistic post-conditions).

**Implications:**

- Tests are deterministic, fast, offline. No API key, no token cost, no flakes.
- The mock IS production-shaped — it writes JSONLs to the same path, honors session UUIDs, supports resume. So `--resume` flows are testable end-to-end without the real model.
- The mock lives at `cmd/stagent-fakeclaude/` and is built alongside the main binary in CI.

Real-Claude integration tests against the live `claude` binary are deferred (see Tabled item D below) — useful for smoke-testing real prompts but not for the main test suite.

### 6. v0.1 milestone scope

Ship the smallest thing that's actually useful: an agent loop with deterministic exit gates, against a single committed task file, with crash safety.

**In v0.1:**

- Event log: schema, append-only triggers, WAL, the three views (`tasks`, `sessions`, `stage_progress`).
- Runner: heartbeat + task workers, PID file, SIGHUP reload, crash recovery via orphan-session detection.
- Stage types: `agent`, `script`. (No `human` yet.)
- Hook slots: `enter`, `exit`. (No `tick` yet.)
- Hooks: `run_shell`, `section_check`, `min_words`, `validate_task_sections`.
- CLI: `init`, `new`, `run`, `status`, `list`, `show`, `log`, `goto`, `abort`, `session`, `restart`.
- Default flow (slimmed): `setup → code → cleanup`. No `pr`, no `review` (because no `human` stage to gate them safely yet).
- Section-path parser (literal + regex segments).
- Scaffold (`stagent init`).

**Deferred to v0.2:**

- Stage type: `human`. `tick` hooks. `wait_for_ci`, `wait_for_merge`, `ci_status`. `human.approved` event.
- `stagent approve`, `stagent poll`, `force_tick`.
- `pr`, `review`, `human_review` stages in the default flow.
- Section_redirect hook (review-loop machinery).

**Deferred to v0.3:**

- SwiftUI viewer.
- `commands:` user recipes.
- More hooks driven by real use.

### 7. Project-language defaults in scaffold

`stagent init` ships a **language-neutral** `.stagent.yaml`. Test/build hooks are commented out with examples per language:

```yaml
exit:
  - validate_task_sections: {}
  # Replace with your project's test command. Examples:
  # - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && go test ./...", fail_on_nonzero: true }
  # - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && npm test", fail_on_nonzero: true }
  # - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && pytest", fail_on_nonzero: true }
  - section_check:
      section: "Implementation plan"
      expect: all_checked
```

No init wizard. No `--lang` flag. The user uncomments the line that fits their stack and moves on.

(Future: see Tabled item 1.)

### 8. Dep-state checks (gating execution) are separate from validation

Validation (decision 3) is about whether the task **file** is well-formed: required sections present, required checkboxes present, no malformed headings. It runs at `stagent new` and again as a `setup` enter hook.

**Dep-state is different.** It's about whether the **world** is in a state where this task should be running *right now*: prerequisite task complete, branch merged, external service ready, lock acquired, time window open. Dep-state can change while the task sits, so it's not a one-shot check at task creation — it's a recurring gate.

**Mechanism (when shipped):** the existing `script` stage + `tick` hooks primitive covers it. A user-defined gating stage at the front of the flow:

```yaml
stages:
  wait_for_deps:
    type: script
    hooks:
      tick:
        - some_dep_hook: { min_interval: 30s, timeout: 24h }

flows:
  default:
    - wait_for_deps
    - setup
    - code
    - ...
```

While the dep hook returns `NotYet`, the task sits in `wait_for_deps`. When it returns `Pass`, the stage completes and the flow advances to `setup`. While waiting, the task shows `status: active`, `current_stage: wait_for_deps` — visible in the viewer and `stagent status`.

**v0.1 status:** because tick hooks are deferred to v0.2, dep-state checks ship in v0.2 as well. The mechanism is the same `script` + `tick` machinery, with one or two built-in dep hooks (TBD based on actual demand) — likely `wait_for_task: { id: <other-task-id> }` and `wait_for_branch_merged: { branch: <name> }`.

No new event type, no new stage type, no new concept. Dep-state is just a script stage that loops until the world is ready.

### 9. `stagent goto` and `max_runs`

`stagent goto <task> <stage>` counts against `max_runs` by default. To override:

```bash
stagent goto <task> <stage> --force [-m "..."]
```

`--force` bypasses the budget AND appends `budget_override: true` to the `stage.entered` event payload. The event log records that a human consciously overrode the budget, so audit reviews can find it later.

---

## Tabled (future, not v0.1)

### A. Per-language scaffolds

Today the scaffold is neutral with commented per-language examples. Once we have real users, it might be worth either:

- A `--lang <name>` flag on `stagent init` that emits a flavored config (`stagent init --lang go` uncomments the Go test/vet lines).
- A `language:` top-level field in `.stagent.yaml` that templates hook commands.

**What actually differs per language** (write this down before deciding):

| Concern | Go | Node | Python | Rust |
|---|---|---|---|---|
| Test command | `go test ./...` | `npm test` / `pnpm test` / `yarn test` | `pytest` / `python -m unittest` | `cargo test` |
| Lint / static analysis | `go vet ./...`, `golangci-lint run` | `npm run lint` (varies) | `ruff` / `pylint` / `mypy` | `cargo clippy` |
| Build | `go build ./...` | `npm run build` (varies) | (none, usually) | `cargo build` |
| Dependency install | `go mod download` | `npm ci` / `pnpm install --frozen-lockfile` | `pip install -r requirements.txt` / `uv sync` | `cargo fetch` |
| Test file conventions | `*_test.go` adjacent | `*.test.{ts,js}` adjacent or `__tests__/` | `tests/` or `test_*.py` | `tests/` or `#[cfg(test)]` adjacent |
| Format check | `gofmt -l` / `goimports -l` | `prettier --check` | `ruff format --check` / `black --check` | `cargo fmt --check` |

The split is along which commands run as `exit` hooks in `code` and `pr` stages. Nothing else in stagent's design varies by language. So: probably ship `--lang <name>` once we have ≥3 real users on ≥2 languages and the friction of "uncomment the right lines" gets annoying.

### B. YAML frontmatter on task files

Currently the task file is plain markdown. Task metadata (id, flow, branch, worktree path) lives in the `task.created` event payload.

Adding frontmatter would let the file carry its own metadata:

```markdown
---
id: 42
flow: hotfix
priority: high
labels: [auth, security]
assignee: dave
---

# Fix login redirect bug
```

**Pro:** the file is self-describing without the DB. Useful if you regenerate state from `tasks/*.md` after losing the SQLite log. Also enables UI affordances (filter by label, sort by priority) without joining against the event log.

**Con:** two sources of truth (frontmatter `flow:` vs event-payload `flow`). Parser dependency (yaml-frontmatter). Less standalone-markdown. Edge cases (what if the frontmatter says `flow: hotfix` but the event says `flow: default`?).

**Decision deferred.** When we add UI features that need filterable metadata, revisit. Until then, the event log is the truth.

### C. Inter-task dependencies

"Task #6 depends on task #5 completing first." Not modeled in v1.

If we add it, the natural shape is either:

- A `depends_on: [5, 7]` frontmatter field that the runner respects (task #6 sits in a `blocked` status until 5 and 7 reach `completed`).
- A separate edges table (`task_deps(parent_id, child_id)`).

For now: linear flow within a task is all we have. If you need ordering between tasks, run them one at a time.

### D. Real-Claude integration smoke tests

The main test suite uses the mock (locked decision 5). A small, separately-tagged suite of smoke tests against the real `claude` binary catches things the mock by definition can't: actual model behavior changes, real session-resume edge cases, real JSONL format drift.

These run with `go test -tags=realclaude`, need `ANTHROPIC_API_KEY`, and are excluded from default CI. Run them manually before releases or as a nightly job.

**Not v0.1.** Build them once the v0.1 mocked suite is solid and we've shipped a binary. Easier to add a small real-Claude smoke test against working code than to debug "did the mock lie?" while bootstrapping.

### E. Global PR-state cache

For projects with many concurrent tasks, individual `wait_for_ci` polls add up. A shared "fetch all PR states for this repo every 60s, distribute to interested tasks" subsystem would amortize the API calls.

Not v1. Per-task `wait_for_ci` + `stagent poll` covers the responsiveness need.

### F. Notifications on `stage.failed`

Slack / email / push. Not built in. Users can wire `run_shell` on a post-completion hook (also not built — would need a new slot).

A built-in `notify_slack` hook would be ~30 lines but: not v1.

### G. Observer agent role

A meta-agent that watches `stage.failed` events and either auto-fixes (resetting the task to a recoverable point) or escalates to human review with a structured explanation. Sits between "budget exhausted" and "human takes over."

Discussed in `notes/architecture.md`. Not v1.

### H. Container isolation

Agents run on the host in v1, inside the task's worktree, with `--dangerously-skip-permissions`. The worktree provides enough isolation for now.

Future: a single shared container scoped to "protect the user's machine," not "protect tasks from each other." Not v1.

---

## Decision changelog

Add a line per substantive change so the implementing agent can see what got revised.

- *2026-05-17* — Initial commit. Decisions 1-9 locked; A-H tabled.
- *2026-05-17* — Decision 5 flipped to **mock Claude** (was: real Claude). Mock-claude binary moves from tabled to locked as a v0.1 deliverable; real-Claude smoke tests become a tabled item (D).
- *2026-05-17* — Added decision 9 (dep-state checks are separate from validation; ship in v0.2 via existing `script` + `tick` primitive).
