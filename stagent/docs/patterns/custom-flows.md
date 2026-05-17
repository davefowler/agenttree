# Pattern: custom flows

The default flow (`setup → code → pr → review → human_review → cleanup`) covers most engineering tasks. For everything else, define your own flow.

## Mechanics

A flow is a named list of stage names:

```yaml
flows:
  default:
    - setup
    - code
    - pr
    - review
    - human_review
    - cleanup

  quick:
    - setup
    - code
    - cleanup
```

When you create a task, pick a flow:

```bash
stagent new "Trivial typo fix" --flow quick
```

A task is locked to its flow at creation — there's no "switch flows mid-task." If you need to deviate, use `stagent goto <task> <stage>` to route manually.

## Defining stages

A flow can reference any stage defined in the `stages:` map. The same stage can appear in multiple flows.

```yaml
stages:
  setup:           { type: script, ... }
  code:            { type: agent,  ... }
  pr:              { type: script, ... }
  review:          { type: agent,  ... }
  security_review: { type: agent,  ... }
  human_review:    { type: human,  ... }
  cleanup:         { type: script, ... }

flows:
  default:
    - setup
    - code
    - pr
    - review
    - human_review
    - cleanup

  with_security:
    - setup
    - code
    - pr
    - review
    - security_review
    - human_review
    - cleanup

  no_review:
    - setup
    - code
    - pr
    - human_review
    - cleanup
```

Adding `security_review` doesn't require changing `default` — just the new flow.

## When to add a flow vs. a stage

- **New flow, existing stages:** when you want to change the *order* or *which stages run* for a class of task. `quick` exists because some tasks don't need a reviewer or a PR.
- **New stage, used in flows:** when you want a *new step* (e.g. `security_review`, `staging_deploy`, `manual_QA`). Define it under `stages:`, then add it to whichever flows want it.

Adding a stage is more work — you need a hook configuration and (if `type: agent`) a role and a stage prompt at `.stagent/prompts/stages/<name>.md`. Adding a flow is just YAML.

## Common variants

### `quick` — typos and trivial fixes

```yaml
quick:
  - setup
  - code
  - cleanup
```

Use case: rename a variable, fix a typo, update a constant. No PR, no review. The developer's session runs once; tests pass; the worktree is removed; done.

The risk: anything where you're tempted to think "this is fine, ship it without review" tends to be the thing that breaks production. Be conservative.

### `local_only` — no GitHub

```yaml
local_only:
  - setup
  - code
  - review
  - human_review
  - cleanup
```

Omits `pr`. Use case: working on a private branch you don't intend to merge upstream, or a project that doesn't use GitHub. The `human_review` stage completes only via `stagent approve` (no `wait_for_merge`).

You'd want to drop the `wait_for_merge` tick hook from `human_review` for this flow — either by defining a second `human_review_local` stage or by making the hook smart enough to skip when no PR exists. Easier: just define two stages.

### `design_first` — for tasks that need a spec round

```yaml
stages:
  draft_spec:
    type: agent
    role: architect
    max_runs: 3
    hooks:
      exit:
        - min_words: { section: "Approach", min: 200 }
        - section_check: { section: "Open questions", expect: all_checked }

  human_spec_review:
    type: human
    max_runs: 1

  # ... code, pr, review, etc. ...

flows:
  design_first:
    - setup
    - draft_spec
    - human_spec_review
    - code
    - pr
    - review
    - human_review
    - cleanup
```

The agent fills in `## Approach` and `## Open questions` before any code is written. A human gates the transition to `code` via `stagent approve`. Once approved, the rest of the flow is identical to default.

This pattern adds two stages and one flow. The developer's session continues from `draft_spec` (if `architect` and `developer` share `bound: task`) — but they probably shouldn't be the same role; architect speaks at a higher level. So they're separate roles with separate sessions, and the `code` stage's developer reads the task file (now including `## Approach`) to pick up where the architect left off.

### `hotfix` — minimal ceremony, maximal speed

```yaml
hotfix:
  - setup
  - code
  - pr
  - cleanup
```

Drops both reviews. `pr` still pushes and waits for CI green (you don't want to ship a broken hotfix). But no agent reviewer, no human review pause. Use when the change is small, the bug is bleeding, and a human is going to merge in GitHub UI manually anyway.

Pair with a stricter `pr` stage:

```yaml
pr:
  type: script
  hooks:
    enter:
      - run_shell: { cmd: "cd {{.Task.WorktreeDir}} && git push -u origin HEAD" }
      - run_shell:
          cmd: "cd {{.Task.WorktreeDir}} && gh pr create --fill --label hotfix"
          fail_on_nonzero: false
    tick:
      - wait_for_ci: { min_interval: 15s, timeout: 10m }   # snappier polling for hotfixes
    exit:
      - ci_status:
          on_failure:
            redirect_to: code
            message_template: "CI failed on hotfix. Fix and re-push. {{.CIFailures}}"
```

## Picking a flow by convention

You can encode flow selection in a `commands:` recipe instead of remembering `--flow`:

```yaml
commands:
  hotfix:
    desc: Start a hotfix task
    run: |
      stagent new "{{.Args}}" --flow hotfix
```

```bash
stagent hotfix "Fix /login 500 in production"
```

Templating supports `.Args` as the post-command argv string. Useful for sugar around common stagent invocations.

## Constraints

- **A flow must have at least one stage.** A zero-stage flow errors at config load.
- **Stage names referenced in a flow must exist in `stages:`.** Typos at config load fail loudly.
- **A flow can repeat a stage name.** This is rarely what you want — usually you want a redirect, not a re-listed stage — but it's allowed. `setup → code → setup → code → cleanup` would enter `setup` twice as `reason: flow`, with each entry counting toward `max_runs`.
- **No conditional inclusion in YAML.** "Run review if the diff is over 100 lines" can't be expressed declaratively. Use a redirect from a script stage instead — define a `gate_review` script stage with a hook that decides whether to redirect to `review` or to `human_review` directly.

## Worked example: gate_review

```yaml
stages:
  gate_review:
    type: script
    hooks:
      exit:
        - run_shell:
            cmd: |
              cd {{.Task.WorktreeDir}}
              LINES=$(git diff origin/main...HEAD --stat | tail -1 | awk '{print $4+$6}')
              if [ "$LINES" -gt 100 ]; then
                exit 0    # normal pass — flow advances to next stage (review)
              else
                exit 42   # special code; the gate_review wrapper hook handles this
              fi
            fail_on_nonzero: true

# ... but this doesn't express "redirect" cleanly with run_shell.
```

`run_shell` only knows pass/fail. To redirect based on diff size, you'd write a small custom Go hook (`diff_size_gate`) that returns `Pass` for "advance normally" or `Redirect("human_review", "diff small enough to skip agent review")` for "skip ahead." See [hooks-reference → Writing a new hook](../configuration/hooks-reference.md#writing-a-new-hook).

Sometimes a script stage with a custom Go hook is cleaner than trying to express logic in flows. Flows declare the *normal* path; redirects + custom hooks express the *conditional* path.
