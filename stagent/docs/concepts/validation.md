# Validation

stagent validates task files against the configured hooks **before** any agent is spawned. The goal: catch authoring errors (missing sections, missing checkboxes, typos in heading text) at the earliest possible moment, so they fail loudly with a fixable error message instead of producing a confusing `stage.failed` deep in the flow.

Validation is **not** the same as dep-state gating — see [the bottom of this page](#validation-vs-dep-state-gating) for the distinction.

## What gets validated

The `validate_task_sections` hook reads the loaded `.stagent.yaml`, walks every hook in every stage in the task's flow, and collects every section path referenced via `section:` or `message_from_section:`. For each reference, it checks:

| Reference shape | Validator requires |
|---|---|
| Literal exact path (e.g. `"Implementation plan"`) | Section exists in the task file. |
| Regex path (e.g. `"Reviews > /^Pass \\d+$/[-1]"`) | The parent segment exists. The regex is allowed to match zero at task-creation time — useful for append-on-each-entry sections like `## Reviews` that have no passes yet. The index `[N]` is parsed for syntactic validity but not range-checked at creation time (the matched set might still be empty). |
| `section_check { expect: all_checked }` with a literal path | Section exists AND contains ≥1 checkbox. Empty checklists fail loudly. |
| `section_check` with a regex path | Parent exists. The checkbox check happens at runtime against the actual matched section. |
| `min_words`, `message_from_section` | Section exists (literal) or parent exists (regex). |

It also checks structural well-formedness of the task file:

- Exactly one H1 (the title).
- No H<n+2> heading without its H<n+1> parent (no `### Foo` directly under H1).
- Heading text unique within its parent (no two `### Notes` under the same H2).

## Two callsites, one implementation

Validation runs in two places, calling the same Go function:

### At `stagent new`

When you register a task — either by file path or by title — the CLI runs the validator before appending the `task.created` event. If anything fails, the CLI prints the errors and exits non-zero. **Nothing lands in the event log.** Fix the task file, re-run.

```
$ stagent new tasks/fix-login.md
✗ Validation failed for tasks/fix-login.md:
  - section 'Implementation plan' has no checkboxes
    (required by hook `section_check` on stage `code`)
  - section 'Review notes' not found
    (referenced by `message_from_section` on stage `review`)

Fix the task file and re-run.
```

This is the fast-feedback path. You wrote the task file, you ran `stagent new`, you get the errors before any session starts, before any worktree is created, before any event is logged.

### As an `enter` hook on `setup`

The same `validate_task_sections` hook is declared as an `enter` hook on `setup` in the default scaffold:

```yaml
stages:
  setup:
    type: script
    hooks:
      enter:
        - validate_task_sections: {}
        - run_shell:
            cmd: "git worktree add {{.Task.WorktreeDir}} -b {{.Task.Branch}} origin/main"
            fail_on_nonzero: true
```

This is defense in depth. It catches:

- **Task file edited after `stagent new`.** You registered the task, then opened the file and deleted a section by accident.
- **Config hot-reloaded with new hook references.** You added a `section_check` referencing a new section, sent `SIGHUP`, and the existing task file doesn't have that section yet.
- **Re-running a task** via `stagent goto <task> setup` after a manual fix.

A failure here is a normal `stage.failed` event with a clear error in the payload. Fix the file, then `stagent goto <task> setup` to retry.

## Errors are batched

The validator reports **every** failure in one pass, not just the first. You shouldn't have to fix one issue, re-run, see the next one, fix it, re-run, etc.

```
✗ Validation failed:
  - section 'Implementation plan' has no checkboxes
  - section 'Review notes' not found
  - heading 'Notes' appears twice under 'Code'
  - H3 'Plan' has no H2 parent
```

## What's NOT validated

- **Content quality.** "Is the Problem section actually descriptive?" — out of scope. The agent reads what's there; the human wrote it. `min_words` exists for "at least N words" if you want a soft lower bound.
- **Plan correctness.** "Is this the right approach to fix the bug?" — that's what the developer's stage prompt is for, not validation.
- **Cross-task consistency.** "Does this task duplicate task #42?" — out of scope.
- **Dep state** — see below.

## Validation vs. dep-state gating

These are different mechanisms answering different questions:

| Concern | Mechanism | When |
|---|---|---|
| **Is the task file well-formed?** | `validate_task_sections` hook | Once at `stagent new`, once at `setup` enter. |
| **Is the world ready for this task to run?** | `script` stage + `tick` hooks (e.g. `wait_for_task`, `wait_for_branch_merged`) | Continuously, until the gate passes. |

Validation is a one-shot check on a static artifact (the task file). Dep-state is a recurring check on an external state that can change.

**Concrete example.** Task #6 fixes the auth bug; task #5 builds the new auth library it depends on. You want task #6 to *exist* now (so the spec is recorded) but not *run* until task #5 ships. The shape:

```yaml
stages:
  wait_for_deps:
    type: script
    hooks:
      tick:
        - wait_for_task:
            id: 5
            min_interval: 1m

flows:
  blocked_by_other:
    - wait_for_deps
    - setup
    - code
    - cleanup
```

```bash
stagent new tasks/006-fix-auth-bug.md --flow blocked_by_other
```

Task #6 enters `wait_for_deps` on the next heartbeat. The tick hook polls every minute; while task #5 hasn't reached `completed`, the hook returns `NotYet`. Once task #5 completes, the next tick returns `Pass`, `wait_for_deps` completes, and task #6 advances to `setup`.

Throughout, task #6 is visible in `stagent status` with `current_stage: wait_for_deps` — clear about why it's not progressing.

Validation doesn't help here — the task file might be perfect. Dep-state is what's blocking. **They're different problems with different mechanisms; don't conflate them.**

**v0.1 status:** validation ships in v0.1; dep-state ships in v0.2 (because it depends on tick hooks, which ship in v0.2). See [decisions.md](https://github.com/davefowler/stagent/blob/main/notes/decisions.md) for milestone scope.
