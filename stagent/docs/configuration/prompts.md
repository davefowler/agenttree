# Prompts

stagent uses two kinds of prompt. Both are plain markdown, both committed to git.

| Kind | Path | Sent | Templating |
|---|---|---|---|
| **Role prompt** | `.stagent/prompts/roles/<role>.md` | Once, as `--system-prompt`, when a Claude session is created for `(task, role)`. | None — same on every task. |
| **Stage prompt** | `.stagent/prompts/stages/<stage>.md` | As the user message on every entry to the stage (initial, retry, redirect, `goto`). | Yes — Go `text/template`. |

The names of the role and stage files match their YAML identifiers. `roles: developer` → `.stagent/prompts/roles/developer.md`. `stages: code` → `.stagent/prompts/stages/code.md`. No per-role or per-stage path overrides.

## Role prompts

Role prompts establish identity and durable context that doesn't change task-to-task:

- Who is this role? (Senior engineer, independent reviewer, etc.)
- What's the project's tech stack and conventions?
- How does stagent work, from the role's perspective?
- What's expected output shape, and what's NOT this role's job?

The role prompt is set **once** per Claude session — when the session is first created (`claude -p ... --system-prompt "$(cat .stagent/prompts/roles/<role>.md)"`). Subsequent `--resume` calls don't re-send it; it persists in the session transcript.

### Example: `roles/developer.md`

The default scaffold ships [`scaffold/.stagent/prompts/roles/developer.md`](https://github.com/davefowler/stagent/blob/main/scaffold/.stagent/prompts/roles/developer.md), which covers:

- Identity: senior software engineer, surgical changes.
- How stagent works: exit signals "done," hooks judge.
- Conventions: stay in the worktree, no PR / push (that's the `pr` stage), no editing `.stagent/`.
- Anti-slop: no features beyond spec, no speculative abstraction, no dead code.

### When to edit

Edit the role prompt when:

- Your project has conventions the agent keeps missing (e.g. "always use snake_case in this codebase," "prefer composition over inheritance," "tests live in `internal/_tests/`").
- You're adding a new role (e.g. `architect` for design-doc stages, `security_reviewer` for security-focused review passes).
- You want to change tone (e.g. "explain decisions verbosely" vs. "be terse").

**Do NOT** put task-specific instructions in a role prompt — those belong in the stage prompt or the task file.

## Stage prompts

Stage prompts are the user message sent on every entry to the stage. They describe the immediate work:

- What to produce.
- Which sections of the task file to fill.
- What prior artifacts to read (the task file, the diff, prior reviews).
- Where to write output.
- Reminder of the convention: exit when done, the system judges.

### Templating

Stage prompts are rendered with Go's `text/template`. Available variables:

| Variable | Meaning |
|---|---|
| `{{.Task.ID}}` | Numeric task ID (e.g. `42`). |
| `{{.Task.Title}}` | Task title as recorded in `task.created`. |
| `{{.Task.Branch}}` | Worktree branch name (e.g. `task-042`). |
| `{{.Task.WorktreeDir}}` | Absolute path to the worktree (e.g. `/abs/.worktrees/task-042`). |
| `{{.Task.Flow}}` | Name of the flow this task is on. |
| `{{.TaskFile}}` | Absolute path to the task's markdown file. |
| `{{.RedirectMessage}}` | The message from a hook redirect, or the body of a `section_check`'s `message_from_section`. Empty on initial entry. |

Use conditional blocks to include redirect context only when relevant:

```markdown
Implement the work described in {{.TaskFile}}.

(... main instructions ...)

{{- if .RedirectMessage }}

## Prior context

{{.RedirectMessage}}
{{- end }}
```

The leading `-` (e.g. `{{- if ...}}`) trims preceding whitespace so the conditional doesn't leave blank lines on initial entry.

### Example: `stages/review.md`

The default scaffold ships [`scaffold/.stagent/prompts/stages/review.md`](https://github.com/davefowler/stagent/blob/main/scaffold/.stagent/prompts/stages/review.md). Key elements:

1. Pointer to the task file (`{{.TaskFile}}`), worktree, and branch.
2. Instructions: read the file, read the diff, evaluate the checklist.
3. On re-review, explicit guidance to check prior passes.
4. Output format: append a new `### Pass N` subsection, structure of each pass, severity rubric.
5. Conditional `## Prior context` block from `{{.RedirectMessage}}`.

## What goes where

A common mistake is putting too much in one or the other. Rule of thumb:

| Information type | Where it goes |
|---|---|
| "You are a senior engineer." | Role prompt. |
| "This project uses Go and follows the style in `STYLE.md`." | Role prompt. |
| "Implement the work in the task file." | Stage prompt. |
| "On a redirect, address feedback before touching new things." | Stage prompt. |
| "Specifics about THIS task: fix the login redirect." | Task file (`## Problem`, `## Context`, `## Implementation plan`). |
| "Reviewer found these issues last pass." | `{{.RedirectMessage}}` — supplied automatically by the hook. |

The role prompt should never know which task is running. The stage prompt should never describe specifics of a particular task. The task file should never duplicate role identity or stage instructions.

## Editing prompts during a task

You can edit prompts mid-flow:

- **Role prompt edits** take effect on the NEXT session (next role-bound-to-task that doesn't have a session yet, or if the role is `bound: stage`, the next stage entry). Sessions that already exist keep their original system prompt.
- **Stage prompt edits** take effect on the next entry to that stage.

To force a role's session to re-pick-up a new role prompt: end the current session manually and let the next stage entry create a fresh one. You can also delete the relevant `session` rows... actually, you can't (events are append-only). The pragmatic answer: live with it, or restart the task.

## Templates vs prompts vs task files

Three things that all look like markdown but mean different things:

| Thing | Audience | Purpose |
|---|---|---|
| `.stagent/templates/task.md` | Humans, via `stagent new "<title>"` | Boilerplate for a new task spec. |
| `.stagent/prompts/stages/<name>.md` | Claude, on stage entry | What the agent should do this turn. |
| `tasks/<id>-<slug>.md` | Both | The actual spec + the actual output. |

The template is **one** file used to seed new task files. The prompts are sent to Claude on every entry. The task file is the work product.
