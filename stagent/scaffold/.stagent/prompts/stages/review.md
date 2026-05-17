Review the developer's work on this task.

- Task file: {{.TaskFile}}
- Worktree: {{.Task.WorktreeDir}}
- Branch: {{.Task.Branch}}

Steps:

1. Read the entire task file. Note the Implementation plan, prior
   Pass sections under `## Reviews` (if any), and the developer's
   `## Code > Notes`.
2. Inspect the diff:

       git -C {{.Task.WorktreeDir}} diff origin/main...HEAD

3. On a re-review (Pass 2+), check whether each item raised in prior
   passes was addressed. If not, raise it again — explicitly note
   which prior pass it came from.
4. Decide each checklist item:
   - Any extra items the task spec preloaded under `## Reviews`
   - "Review approved" — your final verdict; tick this only if every
     other box is ticked AND no critical/high/medium issues remain.
     Low-severity nits do not block approval.
5. Append a new `### Pass N` subsection at the end of `## Reviews`,
   using the next integer N (one more than the highest existing
   pass; start at 1 if none). Shape:

       ### Pass N
       - [ ] (copy any extra items from prior passes or the task spec)
       - [ ] Review approved          ← always the LAST box

       <free-form notes; required only when something needs to change>

   To approve: tick every box. If you found low-severity nits, write
   them under a "**Nits**" sub-block in the notes — they don't block.

   To request changes: leave at least one box UNCHECKED and write
   specific, actionable notes. The whole Pass section (boxes + notes)
   becomes the developer's next prompt. Be precise:

   - file:line references for every issue
   - severity tag (critical / high / medium)
   - "do X" not "consider X"
6. Exit. The exit hook decides — if every box is ticked, the flow
   advances; if any is unticked, the runner redirects to `code` with
   your Pass section as the message.

{{- if .RedirectMessage }}

## Prior context

{{.RedirectMessage}}
{{- end }}
