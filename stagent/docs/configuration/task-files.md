# Task files

Each task is a single markdown file at `tasks/<id>-<slug>.md`. Sections within the file represent stage outputs. Hooks validate by reading those sections — checking that checkboxes are ticked, that minimum word counts are met, that specific section paths exist.

This page covers the conventions, the section-path syntax used by hooks, and the Pass-N pattern for re-reviewable sections.

## One file per task

Everything about a task lives in one markdown file:

- Human-written sections: `## Problem`, `## Context`, `## Possible solutions`, `## Implementation plan`.
- Agent-written sections: `## Code` (developer), `## Reviews` (reviewer).
- Stays committed to git as the authoritative record of what was asked, what was decided, what was done.

The alternative — one file per stage — was tried and rejected. It produces N artifact files per task that have to be read in order to follow the work. The single-file model means anyone reviewing the PR or reading the repo sees the complete journey in one document.

## Default template

`stagent init` ships [`scaffold/.stagent/templates/task.md`](https://github.com/davefowler/stagent/blob/main/scaffold/.stagent/templates/task.md). Stripped of comments:

```markdown
# {{.Task.Title}}

## Problem
(2-3 sentences on the symptom and why it matters now)

## Context
(Background the agent won't infer: file paths, prior work, constraints, links)

## Possible solutions
(1-3 approaches you've considered)

## Implementation plan
- [ ] (Granular task; code stage requires all checked)

## Reviews
(Reviewer appends "### Pass N" here on each entry)

## Code
### Notes
(Developer summarizes what was implemented)
```

You can edit the template freely — but **if you change section headings, update the corresponding `section:` references in `.stagent.yaml`.** The hooks key on heading text.

## Creating tasks

Two paths, both produce `tasks/<id>-<slug>.md`:

### A. Register an existing file

Write the spec in your editor, then:

```bash
stagent new tasks/fix-login.md
```

The file is renamed to `tasks/001-fix-login.md` (or whatever the next ID is), and a `task.created` event is appended.

### B. Start from the template

```bash
stagent new "Fix login redirect bug"
```

A new file is created at `tasks/001-fix-login-redirect-bug.md` from `.stagent/templates/task.md`. Fill it in afterwards. Until the human-written sections are populated, the agent will have less context to work from — but stagent will run the flow either way.

### Choosing a flow

```bash
stagent new "Trivial typo fix" --flow quick
```

Defaults to `default` if `--flow` is omitted.

## Section path syntax (used by hooks)

Hooks reference sections in the task file via a path syntax:

```
"H2-name > H3-name > H4-name ..."
```

Each `>` descends one heading level. Whitespace around `>` is optional.

**Two kinds of segment:**

- **Literal** — exact heading text. Case-sensitive; whitespace inside the name is collapsed (`"Review  Plan"` matches `## Review Plan`).
- **Regex** — wrapped in `/…/`, optionally followed by an array index `[N]`. Matches direct H<parent+1> children whose visible heading text matches the pattern. RE2 syntax (Go's `regexp` package).

Examples:

| Path | Resolves to |
|---|---|
| `"Implementation plan"` | The `## Implementation plan` H2 section (full body). |
| `"Reviews > Pass 1"` | The literal `### Pass 1` H3 under `## Reviews`. |
| `"Code > Notes"` | The `### Notes` H3 under `## Code`. |
| `"Reviews > /^Pass \\d+$/[-1]"` | The **last** H3 under `## Reviews` whose name matches `Pass N`. |
| `"Reviews > /^Pass \\d+$/[0]"` | The **first** matching H3. |
| `"Logs > /^attempt-/[2]"` | The 3rd matching H3 (zero-indexed). |

### Regex segments — for sections that grow over time

The Pass-N review pattern adds new `### Pass N` subsections on every review entry. Hooks need to operate on "the latest one." Express that with a regex segment plus the `[-1]` index:

```yaml
- section_check:
    section: "Reviews > /^Pass \\d+$/[-1]"
    expect: all_checked
```

**Rules:**

- A regex segment is delimited by `/…/`. Inside, use standard [RE2 syntax](https://github.com/google/re2/wiki/Syntax) — no flags suffix (no `/.../i`); use inline `(?i)` if you need case-insensitive matching.
- A regex segment cannot contain `>` (the path separator). In practice heading text won't either; if you genuinely need it, use a character class (`[>]`).
- Regex segments match **direct** H<parent+1> children only — not descendants further down.
- **The index `[N]` is part of the path syntax**, not a separate hook option. Positive N indexes from the start (zero-based); negative N from the end (`[-1]` is the last match).
- **A bare regex without `[N]` must match exactly one section** at runtime. Multiple matches → `Fail("regex matched N sections; specify an index")`. Zero matches → `Fail("regex matched no sections")`.
- **An out-of-range index** at runtime (e.g. `[5]` when only 2 sections match) → `Fail("regex match index N out of range; got K matches")`.
- **Exception**: at task creation, the validator allows zero matches on any regex segment — useful for sections that grow over time like `## Reviews` (the validator can't predict how many Pass N entries the reviewer will produce).

**Literal segments must match exactly one section.** Zero matches or multiple matches are authoring errors caught by the validator (see [Validation](../concepts/validation.md)).

### Checkbox parsing

Lists like `- [ ]` and `- [x]` are parsed as task list items:

- `- [ ]` → unchecked
- `- [x]` or `- [X]` → checked (case-insensitive)

HTML comments (`<!-- ... -->`) inside a section are ignored when checking — so explanatory comments in the template don't count as content and don't break checkbox enumeration.

`section_check { expect: all_checked }` passes only when every item in the section is checked. **An empty section (zero list items) is a `Fail`** — it almost always means the agent didn't write what it was supposed to. If you really want "this section is allowed to be empty," don't put a `section_check` on it.

## The Pass-N review pattern

The `review` stage is special: it can re-enter the same task multiple times (when CI redirects, when the reviewer rejects, when a human pushes back). Each entry appends a **new** `### Pass N` subsection under `## Reviews`. Prior passes stay in place as audit trail.

```markdown
## Reviews

### Pass 1
- [ ] Tests cover the new behavior on the primary path
- [x] Public API changes are documented
- [ ] Review approved

The retry logic in client.go:142 swallows network errors silently —
return them. **Severity: high.**

### Pass 2
- [x] Tests cover the new behavior on the primary path
- [x] Public API changes are documented
- [x] Review approved

LGTM.
```

The hook keys on the **latest** pass:

```yaml
- section_check:
    section: "Reviews > /^Pass \\d+$/[-1]"
    expect: all_checked
    on_fail:
      redirect_to: code
      message_from_section: "Reviews > /^Pass \\d+$/[-1]"
```

If the latest pass has any unchecked box, the whole section (boxes + notes) becomes the redirect message back to the developer. They see exactly what's not approved and what the reviewer wrote.

### Severity rubric

By convention (encoded in the reviewer prompt), each reviewer-raised issue carries one of four severities:

| Severity | Meaning |
|---|---|
| **critical** | Data loss, security hole, will break in production. |
| **high** | Wrong behavior on a documented path, regression. |
| **medium** | Correctness gap on an edge case, missing test for the primary path, API contract issue. |
| **low / nit** | Style, naming, micro-perf, doc typos. |

"Review approved" ticks **only when no critical / high / medium issues remain.** Low-severity nits do not block approval — the reviewer groups them under a "Nits" sub-block in their notes, and the developer addresses them or not.

This convention is in the [reviewer role prompt](https://github.com/davefowler/stagent/blob/main/scaffold/.stagent/prompts/roles/reviewer.md) — change the prompt to use a different rubric if you like, but keep the convention consistent across reviews.

### Why append-only

Three reasons the Pass-N pattern beats "clear between passes":

1. **Matches the append-only design tenet.** The event log doesn't UPDATE; documents shouldn't either.
2. **Re-reviewers can verify prior concerns.** "Did the developer actually fix what I asked for last time?" requires seeing what was asked.
3. **Git diff tells the story.** When a PR includes a task file's evolution, you can read the full review history without leaving the file.

## Filling sections by hand

Nothing stops you from editing the task file mid-flow. Common reasons:

- **You realize the Implementation plan is wrong.** Edit it. On the next `code` entry (or via `stagent goto <id> code -m "plan updated"`), the developer picks up the new plan.
- **The reviewer rejected for a reason you disagree with.** Edit the latest Pass section to tick the box and reduce the developer's churn — or run `stagent approve <id>` (only works on human stages) — or just hand-edit Pass N to address one concern but leave the others.
- **You want to add context the agent missed.** Append a `## Context` paragraph; on the next stage entry, the agent reads the full file.

This is intentional. The task file is the spec; you're allowed to edit the spec.

## What NOT to do

- **Don't rename sections without updating `.stagent.yaml`.** Hooks key on heading text; a rename breaks the hooks silently (the section won't be found, and `section_check` will likely fail "vacuously satisfied" or with a "section not found" error depending on configuration).
- **Don't delete prior `### Pass N` blocks.** The audit trail is the whole point. If a pass is irrelevant, leave it.
- **Don't put structured data outside sections.** The first line should be `# <title>`; everything after lives under an H2. Free-floating prose between H2s gets ignored by every hook.
- **Don't store secrets in task files.** They're committed to git. Use environment variables or your project's secret-management story.
