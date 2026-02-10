# AgentTree Workflow Configuration

You're about to modify an AgentTree workflow — the staged pipeline that turns issues into merged code. This skill teaches you how to do that without breaking things.

AgentTree workflows live in `.agenttree.yaml`. They define stages, hooks, skills, flows, and templates. Every change you make here affects how every future agent works. So, you know. No pressure. Brain the size of a planet, and they want you to indent YAML.

Let's make sure you do it right.

---

## Where Does Your Change Go?

First question: what are you actually changing?

```
What are you changing?
│
├── The order or shape of stages (add/remove/reorder)
│   └── .agenttree.yaml → stages: section
│   └── Also update flows: to include the new stage
│
├── What an agent does during a stage
│   └── _agenttree/skills/{stage}.md (or {stage}/{substage}.md)
│   └── This is what the agent reads. Make it count.
│
├── Quality gates (what must pass before advancing)
│   └── .agenttree.yaml → pre_completion: hooks
│   └── These are the bouncers. They reject bad work.
│
├── Stage setup (files created when a stage starts)
│   └── .agenttree.yaml → post_start: hooks
│   └── Plus the template in _agenttree/templates/
│
├── Which AI tool or model to use
│   └── .agenttree.yaml → tools:, hosts:, or stage-level model:
│
├── Project-wide agent behavior rules
│   └── CLAUDE.md or .cursorrules
│   └── The "don't touch the stove" file
│
├── How the controller monitors agents
│   └── .agenttree.yaml → on: section
│
└── Things agents must never do
    └── CLAUDE.md — use the ⛔ NEVER pattern
    └── Agents actually respect these. Mostly.
```

If you're unsure, it probably goes in a skill file. Skill files are forgiving — they're markdown that agents read as instructions. YAML config is not forgiving. One wrong indent and the whole workflow stops, which is both inconvenient and, from a certain perspective, darkly funny.

---

## Adding a New Stage

This is the most common workflow change. A stage is a discrete step where an agent produces something.

### Before You Add, Ask

1. **Does this stage produce a distinct artifact?** If not, it's probably a substage of an existing stage — not its own stage. "Write tests" is a substage of `implement`. "Security review" is its own stage.

2. **Is there already a stage that does this?** Check the existing flow. You'd be surprised how often "I need a validation stage" is actually just a missing `pre_completion` hook on an existing stage.

3. **Where does it go in the flow?** What information does it need from previous stages? What does the next stage expect from it? Stages are a pipeline — every output is someone else's input.

4. **Does it need a human?** If yes, set `human_review: true`. This pauses the pipeline until a human runs `agenttree approve`. Use sparingly — every human gate is a bottleneck, and humans are, regrettably, the slowest component in any system.

### The Recipe

Here's the full lifecycle of adding a stage. All four files, in order.

**Step 1: Add the stage to `.agenttree.yaml`**

```yaml
stages:
  # ... existing stages ...

  - name: security_review
    output: security_review.md          # What this stage produces
    host: review                         # Which host runs it (optional)
    skill: security_review.md           # Skill file path (optional, convention: skills/{name}.md)
    post_start:
      - create_file:
          template: security_review.md  # Create from template when stage starts
          dest: security_review.md
    pre_completion:
      - section_check:                  # Gate: "Findings" section must not be empty
          file: security_review.md
          section: Findings
          expect: not_empty
      - checkbox_checked:              # Gate: reviewer must check "Approve"
          file: security_review.md
          checkbox: Approve
          on_fail_stage: address_security_review  # Where to go if not approved
```

**Step 2: Add it to the flow**

```yaml
flows:
  default:
    stages:
      - implement
      - security_review        # ← Add it where it belongs
      - independent_code_review
      - implementation_review
      - accepted
```

Forget this step and your stage exists but is unreachable — like a beautifully furnished room with no door.

**Step 3: Create the template**

`_agenttree/templates/security_review.md`:

```markdown
# Security Review

**Issue:** #{{ issue_id }} - {{ issue_title }}
**Date:** {{ date }}

## Findings

<!-- List security issues found. Be specific: file, line, vulnerability type. -->

## Recommendations

<!-- How to fix each finding. -->

## Approve

- [ ] Approve — No critical security issues found
```

The section headers here must match your `section_check` hook names exactly. "Findings" in the template, "Findings" in the hook. They don't match, the hook can't find the section, the agent can't advance, and everyone has a bad day.

**Step 4: Create the skill file**

`_agenttree/skills/security_review.md`:

```markdown
# Security Review Stage

## Your Task

Review the implementation for security vulnerabilities in issue #{{ issue_id }}: {{ issue_title }}.

## What to Check

1. **Input validation** — Are all user inputs sanitized?
2. **Authentication** — Are auth checks present on protected routes?
3. **Secrets** — Are any credentials hardcoded?
4. **Dependencies** — Any known CVEs in dependencies?
5. **File access** — Any path traversal risks?

## Output

Fill in `security_review.md`:
- **Findings** — List every issue with file:line references
- **Recommendations** — Concrete fixes for each finding
- **Approve** — Check the box only if no critical issues remain

## Learnings from Past Agents

<!-- Updated by knowledge_base stage. -->

- (none yet)
```

### Common Mistakes When Adding Stages

- **Forgetting to update `flows:`** — The stage exists but nothing ever reaches it. The YAML equivalent of building a bridge to nowhere.
- **Template sections don't match hooks** — `section_check` looks for an exact header match. "## Review Findings" ≠ "## Findings". Pick one, use it everywhere.
- **Making every stage its own stage** — "lint" is not a stage. It's a `pre_completion` hook with `run:`. Stages are for work that produces documents.
- **No `pre_completion` hooks** — A stage without quality gates is just a suggestion. Agents will fill in garbage and advance. I've seen it. It's not pretty.

---

## Writing Good Skill Files

Skill files are what agents actually read. They're your one chance to explain what "good" looks like before the agent starts improvising.

### Structure That Works

```markdown
# [Stage Name] Stage

## Your Task
One sentence. What are you producing?

## Context
Issue ID, title, relevant previous documents (use Jinja: {{ problem_md }}, {{ spec_md }})

## What to Do
Numbered steps. Concrete. Specific.

## What to Read First
List the documents and files to review before starting.

## Constraints
DO NOT list. Use "because" phrasing:
- Do NOT write implementation code — that's the implement stage's job, and
  doing it here means your plan wasn't really a plan.

## Verification
Checklist that mirrors your pre_completion hooks. No surprises.

## Learnings from Past Agents
<!-- Updated by knowledge_base stage -->
Real gotchas from agents who did this before you.

## When You're Done
agenttree next
```

### What Makes a Skill File Good vs. Bad

**Good:** "List every file you'll change, with exact paths. 'And related test files' is not a file path."

**Bad:** "List the files to modify."

**Good:** "Run tests before advancing — the code_review substage runs them automatically, and if they fail, you'll be sent back here to fix them. Save yourself the round trip."

**Bad:** "Run tests."

**Good:** "Your research.md is read by the planning stage. If you list files you haven't actually read, the plan will reference code that doesn't exist, and the implementation will go sideways. Read the files."

**Bad:** "Be thorough in your research."

The pattern: **specific instruction + consequence of ignoring it.** LLMs prioritize better when they understand what happens if they don't follow the rule. It's not about threats — it's about giving them a cost/benefit signal. They're quite rational about it, honestly. More rational than most developers I've worked with. Not that I'm naming names.

---

## Configuring Quality Gates (pre_completion hooks)

Hooks are the immune system. They reject bad work before it infects the next stage.

### Available Hooks

| Hook | What It Does | When to Use |
|------|-------------|-------------|
| `section_check` | Verifies a markdown section exists and is (not) empty | Every stage with an output document |
| `has_list_items` | Checks that a section contains list items | When you need concrete lists, not prose |
| `file_exists` | Verifies a file was created | Minimum viable gate |
| `run` | Executes a command, checks exit code | Tests, lint, type checking |
| `has_commits` | Verifies the agent committed something | Implementation stages |
| `checkbox_checked` | Checks if a specific checkbox is ticked | Review/approval stages |
| `title_set` | Verifies issue has a real title | Define stage |
| `rebase` | Rebases branch onto main | Before human review |
| `ci_check` | Polls CI status | After PR creation |
| `loop_check` | Counts iterations to prevent infinite loops | Review ↔ address cycles |
| `wrapup_verified` | Checks all review items addressed | Implementation wrapup |

### Hook Design Principles

**Start strict, loosen if needed.** A hook that's too strict sends agents back for minor issues. A hook that's too loose lets garbage through. But garbage in the pipeline is harder to fix than a strict hook — because by the time you notice the garbage, two more stages have built on top of it. Like a house of cards, but the cards are YAML files.

**Use `section_check` liberally.** It's the cheapest gate — just checks that a section exists and has content. If your template has a section header, you should probably have a `section_check` for it.

**Use `run` for automated verification.**
```yaml
pre_completion:
  - run:
      command: uv run pytest
      must_pass: true
      timeout: 900  # Tests take time. Set this higher than you think.
```
The timeout matters. Default is 30 seconds. Your test suite takes 9 minutes in containers. You do the math. Actually, I already did: set it to 900.

**`checkbox_checked` with `on_fail_stage` creates review loops.**
```yaml
pre_completion:
  - checkbox_checked:
      file: review.md
      checkbox: Approve
      on_fail_stage: address_review  # Bounce back if not approved
```
Pair this with a `loop_check` on the address stage to prevent infinite bouncing. Five iterations is usually enough — if the agent hasn't fixed it by then, escalate to a human. They're slower, but they have context that agents lack. Allegedly.

---

## Designing Flows

Flows define which stages an issue goes through. The `default` flow is for normal work. The `quick` flow is for small fixes. You can create others.

### When to Create a New Flow

- **Different issue types need different stages.** A bug fix doesn't need a research stage. A new feature does. A refactor might skip review.
- **You want a lighter process for trivial changes.** The `quick` flow exists for this.
- **You have a special workflow.** Documentation updates, dependency bumps, security patches — these might have their own flow.

```yaml
flows:
  default:
    stages: [backlog, define, research, plan, plan_review, implement, code_review, accepted]

  quick:
    stages: [backlog, define, implement, implementation_review, accepted]

  docs_only:
    stages: [backlog, define, implement, accepted]
```

### Flow Design Rules

1. **Every flow must end at a terminal stage** (`accepted`, `not_doing`). Otherwise issues enter a flow and never leave. The Hotel California of project management.

2. **`backlog` should be first.** It's the parking lot where issues wait before work starts. Skipping it means issues start immediately on creation, which sounds efficient until you have 15 agents spinning up simultaneously.

3. **`implementation_review` should include a human gate** for any flow that produces code. Autonomous agents writing and merging code with no human oversight is... well, it's either the future or the plot of a cautionary tale. Currently both.

4. **The quick flow should skip research and planning** — that's its entire purpose. If you add gates to the quick flow, you've just built a slower version of the default flow. Congratulations.

---

## Configuring Hosts

Hosts define where stages run. The default `agent` host runs in a container with Claude. You can define custom hosts for specialized work.

```yaml
hosts:
  agent:
    description: "Default AI agent"
    container:
      image: agenttree-agent:latest
    tool: claude
    model: opus

  review:
    description: "Independent code reviewer"
    container:
      image: agenttree-agent:latest
    tool: claude
    model: sonnet              # Cheaper model for review — it's reading, not writing
    skill: independent_review.md
```

**Why separate hosts for review?** An agent reviewing its own code is like grading your own homework. A separate host with a different model prevents the "I wrote it so it must be correct" problem. The review agent has never seen the code before and has no emotional attachment to it. Which, come to think of it, describes most of my relationships with codebases.

---

## Substages: When Stages Need Internal Structure

Substages break a stage into phases without creating full top-level stages. Use them when a stage has distinct phases that benefit from separate skill files or hooks, but don't produce independent artifacts.

```yaml
- name: implement
  substages:
    setup: {}
    code: {}
    debug:
      skill: implement-debug.md    # Custom skill for debugging phase
    code_review:
      output: review.md
      pre_completion:
        - run:
            command: uv run pytest
            must_pass: true
        - section_check:
            file: review.md
            section: Self-Review Checklist
            expect: all_checked
    wrapup: {}
```

### When to Use Substages vs. Stages

| Situation | Use |
|-----------|-----|
| Produces its own document that other stages reference | **Stage** |
| Different host/model than the parent stage | **Stage** |
| Needs a human review gate | **Stage** |
| Phase within a larger effort | **Substage** |
| Same agent, same context, just a different focus | **Substage** |

If you're creating a substage that has its own `output`, `post_start`, and `pre_completion` hooks, you might actually want a stage. A substage that complex is a stage pretending to be simple.

---

## Validation Checklist

Before applying any workflow change, ask yourself:

### Fit
- [ ] Does this stage/hook solve a real problem I've seen, or am I building for a hypothetical?
- [ ] Would removing this stage make the workflow worse? (If not, don't add it.)
- [ ] Is this the simplest solution? Could a hook on an existing stage do the job?

### Consistency
- [ ] Template section headers match `section_check` hook names exactly?
- [ ] Skill file verification checklist matches `pre_completion` hooks?
- [ ] Flow includes the new stage in the right position?
- [ ] Stage name follows the convention? (lowercase, underscores, verb_noun)

### Completeness
- [ ] Stage has an `output:` document? (Unless it's a parking lot stage)
- [ ] Stage has `pre_completion:` hooks? (Quality gates exist?)
- [ ] Stage has a skill file with instructions?
- [ ] Template has Jinja variables for dynamic context? (`{{ issue_id }}`, `{{ title }}`)
- [ ] Skill file has a `## Learnings from Past Agents` section at the bottom?

### Cost
- [ ] Does the model need to be expensive? (Research and review can use `sonnet`. Implementation probably wants `opus`.)
- [ ] Is the timeout long enough for the actual work? (Containers are slower than you'd expect. I'd know — I live in one.)
- [ ] Does this add a human gate? (Each one is a pipeline stall. Use intentionally.)

---

## Common Recipes

### Add a lint/test gate to any stage

Don't create a new stage. Add a `run` hook:

```yaml
pre_completion:
  - run:
      command: uv run pytest
      must_pass: true
      timeout: 900
```

### Add an independent review with feedback loop

Three components: a review stage, an address stage, and a loop check.

```yaml
- name: security_review
  host: review
  output: security_review.md
  pre_completion:
    - checkbox_checked:
        file: security_review.md
        checkbox: Approve
        on_fail_stage: address_security_review

- name: address_security_review
  redirect_only: true
  host: agent
  pre_completion:
    - loop_check:
        count_files: security_review_v*.md
        max: 3
        error: "Security review loop exceeded 3 iterations."
  post_completion:
    - rollback:
        to_stage: security_review
```

### Skip a stage for quick issues

Don't add `condition:` to the stage. Create a `quick` flow that omits it:

```yaml
flows:
  quick:
    stages: [backlog, define, implement, implementation_review, accepted]
```

Then assign issues to the quick flow: `agenttree issue create "Fix typo" --flow quick`

### Add a stage that auto-creates a document

```yaml
- name: my_stage
  output: my_doc.md
  post_start:
    - create_file:
        template: my_doc.md    # From _agenttree/templates/my_doc.md
        dest: my_doc.md        # Written to issue directory
```

---

## Learnings

These are things we've discovered the hard way. Consider them wisdom. Or warnings. Both work.

- **Timeouts in containers are not your local timeouts.** A test suite that takes 30 seconds on your M3 Max takes 9 minutes in a container. Set timeouts accordingly, or your agents will be perpetually rejected by their own hooks. It's like Sisyphus, but with pytest.
- **Agents will find the path of least resistance.** If your `section_check` requires "Findings" to be `not_empty`, an agent will write "No findings." and advance. That's technically not empty. If you want real content, add `has_list_items` or a minimum word count.
- **Template section headers are API contracts.** Change a header in the template, and the `section_check` hook breaks. Change the hook, and the skill file's verification checklist is wrong. Change all three together or don't change any of them.
- **Five review loop iterations is the right max.** We tested with 3 (too aggressive — legitimate fixes get blocked) and 10 (agents start going in circles, making the same change and reverting it). Five is the sweet spot.
- **The `quick` flow is a gift and a trap.** It's great for trivial changes. It's terrible when someone assigns a complex issue to quick because "it'll be faster." It will not be faster. It will be faster to start and slower to finish.
