# {{.Task.Title}}

<!--
This is your task spec. Fill it in before running stagent (or have stagent
start, pause, and edit while it works — your call).

Sections are wired to the workflow:
  - Problem, Context, Possible solutions   ← human-written, planning context
  - Implementation plan                    ← human-written checklist; code stage
                                             must check every box to complete
  - Review plan                            ← reviewer must check "Review approved";
                                             if not, "Review notes" becomes the
                                             redirect message back to the developer
  - Code, Review                           ← agents fill these in during execution

Comments like this one (HTML comments) are ignored. Delete or keep them.
-->

## Problem

<!--
What problem are we solving? 2-3 sentences. Be specific:
  - What's the symptom?
  - Who feels it?
  - Why does it matter now?
-->

## Context

<!--
Relevant background the agent won't infer from the codebase alone:
  - Where the affected code lives (file paths, modules)
  - Past attempts, related work, prior discussion
  - Constraints (performance, compatibility, security, deadlines)
  - Links to issues, designs, threads
-->

## Possible solutions

<!--
Sketch 1-3 approaches you've considered. Doesn't have to be exhaustive.
This shapes how the agent thinks; without it, the agent picks one
unilaterally and you may not like the choice.

If one approach is clearly best, say so. The agent will pick that one.
-->

## Implementation plan

<!--
Concrete checklist of what needs to happen. The `code` stage's
section_check hook requires every box here to be checked before the
stage can complete — so make them granular enough that "all checked"
genuinely means "done".

The developer agent checks items off as it completes them. On a
redirect-loop back from review or CI, the agent sees which boxes
remain unchecked and continues.
-->

- [ ] (Replace with the first concrete task)
- [ ] (Add more granular items as needed)

## Review plan

<!--
What the reviewer must approve. The default is one box:
"Review approved." If you want the reviewer to verify specific things
(coverage, perf, docs updated), add more boxes here.

If the reviewer wants changes instead of approving, they leave
"Review approved" UNchecked and write feedback in "Review notes"
below. The hook then redirects back to `code` with those notes
prepended to the developer's next prompt.
-->

- [ ] Review approved

## Review notes

<!--
Empty if approved. If review is NOT approved, the reviewer writes
what needs to change here, and the text becomes the message the
developer sees when resumed.
-->

## Code

<!--
Filled in by the developer agent during the `code` stage. The agent
appends notes about what was implemented, why this approach, and any
deviations from the Implementation plan.
-->

### Notes

<!-- Implementation notes go here. -->
