# {{.Task.Title}}

<!--
This is your task spec. Fill it in before running stagent (or have stagent
start, pause, and edit while it works — your call).

Sections are wired to the workflow:
  - Problem, Context, Possible solutions   ← human-written, planning context
  - Implementation plan                    ← human-written checklist; the
                                             code stage must check every
                                             box to complete
  - Reviews                                ← reviewer appends "### Pass N"
                                             on each review entry; the
                                             section_check hook keys on
                                             the latest pass. Prior passes
                                             stay as audit trail.
  - Code                                   ← developer agent fills this

Comments like this one (HTML comments) are ignored by hooks. Delete or
keep them as you like.
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

## Reviews

<!--
On every entry to the `review` stage, the reviewer appends a new
"### Pass N" subsection here. The section_check hook matches Pass
sections via regex (`Reviews > /^Pass \d+$/`) and picks the latest
in document order. Prior passes stay in place as audit trail.

Each Pass section is a checklist followed by free-form notes. If any
box in the latest pass is unchecked, the whole Pass section becomes
the redirect message back to the developer.

"Review approved" is the FINAL checkbox — the reviewer evaluates each
specific criterion first, then ticks "approved" only if every prior
box is also ticked AND there are no critical, high, or medium severity
issues remaining in the notes. Low-severity nits do NOT block
approval; the reviewer can note them under a "Nits" sub-block for the
developer to consider but should still tick "approved."

Severity rubric:
  - critical:  data loss, security hole, will break in production
  - high:      wrong behavior on a documented path, regression
  - medium:    correctness gap on an edge case, missing test for the
               primary path, API contract issue
  - low / nit: style, naming, micro-perf, doc typos

Lint, formatting, and type errors are caught by CI in the `pr` stage —
do NOT add boxes for them here.

To customize the first pass, un-comment the block below and add any
project-specific must-verify items above "Review approved":

  ### Pass 1
  - [ ] Tests cover the new behavior on the primary path
  - [ ] Public API changes are documented
  - [ ] Review approved
-->

## Code

<!--
Filled in by the developer agent during the `code` stage. The agent
appends notes about what was implemented, why this approach, and any
deviations from the Implementation plan.
-->

### Notes

<!-- Implementation notes go here. -->
