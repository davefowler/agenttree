Implement the work described in this task.

- Task file: {{.TaskFile}}
- Worktree: {{.Task.WorktreeDir}}
- Branch: {{.Task.Branch}}

Steps:

1. Read the entire task file. Pay particular attention to
   "Implementation plan" — every box there must end up checked
   before you exit.
2. If this is a re-entry (you'll see a "Prior context" block below),
   address that feedback first before touching anything new.
3. Implement. Commit cleanly to your worktree's branch (commits stay
   local; the `pr` stage handles pushing).
4. Run the project's tests, lint, and type checker. The exit hooks
   will run these too — if you exit with anything red, you'll come
   back with the failure output prepended.
5. As you complete items in "Implementation plan", tick them off
   (`- [ ]` → `- [x]`). The exit hook requires all of them ticked.
6. Append a short summary of what you did under `### Notes` inside
   the `## Code` section of the task file. Cover: what you changed,
   why this approach, anything that surprised you, deviations from
   the Implementation plan and why.
7. Exit when done. The system judges — you don't.

{{- if .RedirectMessage }}

## Prior context

{{.RedirectMessage}}
{{- end }}
