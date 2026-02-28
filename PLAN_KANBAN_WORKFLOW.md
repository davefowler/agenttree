# Plan: Kanban Workflow with Separate Agents Repo

**Status:** Planning
**Goal:** Build simple kanban web UI with spec-driven TDD workflow, one agent per task, local CI enforcement

---

## Overview

Replace GitHub-centric workflow with a custom kanban board backed by a separate `_agenttree/` repository. Each issue moves through well-defined stages with automated scripts handling busy work and stage-specific skills guiding agents.

---

## Kanban Stages

### Main Stages

1. **Backlog** - Issues waiting to be worked on
2. **Problem** - Understanding the problem deeply
3. **Problem Review** - User reviews problem statement
4. **Research/Brainstorm/Plan** - Design the solution
5. **Plan Review** - User reviews implementation plan
6. **Implement** - Build the solution with TDD
7. **Implementation Review** - Code review + CI
8. **Accepted** - Done ✅
9. **Not Doing** - Rejected ❌

### Sub-Stages (for agent guidance)

**Problem (Stage 1)**
- 1a: Read issue and context
- 1b: Ask clarifying questions (if needed)
- 1c: Write problem statement document
- 1d: Define acceptance criteria

**Problem Review (Stage 2)**
- 2a: User reviews problem doc
- 2b: Agent addresses feedback
- 2c: User approves → move to stage 3

**Research/Brainstorm/Plan (Stage 3)**
- 3a: Explore codebase for relevant files
- 3b: Research approaches/patterns
- 3c: Write implementation plan
- 3d: Identify risks and unknowns

**Plan Review (Stage 4)**
- 4a: User reviews plan
- 4b: Agent addresses feedback
- 4c: User approves → move to stage 5

**Implement (Stage 5)**
- 5a: Setup branch and environment
- 5b: Write failing tests (TDD)
- 5c: Implement to make tests pass
- 5d: Add edge cases
- 5e: Refactor and clean up
- 5f: Add documentation/comments

**Implementation Review (Stage 6)**
- 6a: Run quick_ci.sh locally
- 6b: Run ci.sh (full test suite)
- 6c: Self-review changes
- 6d: Run Claude review (API call)
- 6e: Address review feedback
- 6f: Run extensive_ci.sh
- 6g: User final approval → move to accepted

**Accepted (Stage 7)**
- Issue complete
- Agent worktree freed
- Docs archived

**Not Doing (Stage 8)**
- Issue rejected/cancelled
- Agent freed immediately

---

## Repository Structure

### _agenttree/ Repository

```
_agenttree/
├── .git/                      # Separate git repo
├── issues/                    # One dir per issue
│   ├── 001-login-bug/
│   │   ├── issue.yaml         # Metadata (stage, assigned agent, dates)
│   │   ├── problem.md         # Problem statement (stage 1)
│   │   ├── plan.md           # Implementation plan (stage 3)
│   │   ├── review.md         # Code review notes (stage 6)
│   │   └── commit-log.md     # What was done (stage 5+)
│   ├── 002-dark-mode/
│   └── archive/              # Completed issues moved here
├── templates/                # Templates for each stage
│   ├── problem.md
│   ├── plan.md
│   ├── review.md
│   └── commit-log.md
├── scripts/                  # Helper scripts
│   ├── new-issue.sh          # Create new issue
│   ├── edit-issue.sh         # Pull, edit, push
│   ├── move-stage.sh         # Move to next stage
│   └── review-issue.sh       # Call Claude review API
└── skills/                   # Stage-specific agent skills
    ├── 1-problem/
    │   └── understand-problem.md
    ├── 3-research/
    │   └── explore-codebase.md
    ├── 5-implement/
    │   └── tdd-workflow.md
    └── 6-review/
        └── self-review.md
```

### Main Repository

```
myproject/
├── .git/
├── src/
├── tests/
├── _agenttree/                   # Git submodule → agents repo
├── scripts/
│   ├── quick_ci.sh          # Fast checks (lint, format)
│   ├── ci.sh                # Standard test suite
│   └── extensive_ci.sh      # Full integration tests
└── .agenttree/
    ├── config.yaml
    └── skills/              # Symlink to _agenttree/skills/
```

---

## Workflow: One Agent Per Task

### Principle

**One agent exclusively works on one issue until completion.**

No task switching, no "pick up work later". Simplifies everything:
- Agent worktree = issue worktree
- Agent status = issue status
- When issue moves to "Accepted", agent becomes available

### Agent Assignment

```bash
# User assigns issue to agent
agenttree assign 1 42

# Creates:
# 1. _agenttree/issues/042-title/ directory
# 2. Worktree at ~/Projects/worktrees/agent-1/
# 3. Starts agent in tmux with stage 1 instructions
```

### Stage Transitions

Each stage transition:
1. Pulls _agenttree/ repo
2. Updates `issue.yaml` with new stage
3. Commits and pushes
4. Loads new stage-specific skills
5. Agent continues work

```bash
# Agent calls this when ready
agenttree next-stage

# Script:
# - Validates current stage is complete
# - Updates issue.yaml
# - git commit + push
# - Loads next stage skills
# - Notifies agent
```

---

## Web UI: Simple Kanban Board

### Tech Stack

- **Backend:** FastAPI (already using)
- **Frontend:** HTMX + minimal JS for drag-drop
- **State:** _agenttree/ git repo (backend pulls latest on each request)

### Features

**Kanban Board View**
```
┌─────────┬─────────┬──────────┬─────────┐
│ Backlog │ Problem │ Research │ Implement│ ...
├─────────┼─────────┼──────────┼─────────┤
│ #042    │ #038    │ #035     │ #030    │
│ Login   │ Dark    │ Search   │ Auth    │
│         │ mode    │          │         │
│ #043    │         │ #036     │         │
│ ...     │         │          │         │
└─────────┴─────────┴──────────┴─────────┘
```

**Card UI**
- Issue number + title
- Assigned agent badge
- Current sub-stage (e.g., "5c: Implementing")
- Last updated time

**Drag & Drop**
- Drag card to new column
- POST to backend: `/api/issues/{id}/move?stage=3`
- Backend updates issue.yaml and commits
- Reload board

**Modal for Issue Detail**
- Click card → modal opens
- Shows all docs: problem.md, plan.md, etc.
- Edit button → pulls, opens editor, pushes on save
- Markdown rendered with syntax highlighting

**Navigation**
```
┌──────────────────────────────────────────┐
│ AgentTree | Dashboard | Kanban | Agents  │
└──────────────────────────────────────────┘
```

---

## Helper Scripts

### scripts/new-issue.sh

```bash
#!/bin/bash
# Create a new issue in _agenttree/ repo

cd _agenttree/
git pull origin main

ISSUE_NUM=$(find issues/ -maxdepth 1 -type d | wc -l)
ISSUE_NUM=$((ISSUE_NUM + 1))
ISSUE_SLUG="$1"  # e.g., "login-bug"

mkdir -p "issues/$ISSUE_NUM-$ISSUE_SLUG"

cat > "issues/$ISSUE_NUM-$ISSUE_SLUG/issue.yaml" <<EOF
number: $ISSUE_NUM
title: "$2"
stage: backlog
assigned_agent: null
created_at: $(date -Iseconds)
updated_at: $(date -Iseconds)
EOF

git add "issues/$ISSUE_NUM-$ISSUE_SLUG"
git commit -m "Create issue #$ISSUE_NUM: $2"
git push origin main

echo "Created issue #$ISSUE_NUM"
```

### scripts/move-stage.sh

```bash
#!/bin/bash
# Move issue to next stage

ISSUE_NUM=$1
NEW_STAGE=$2

cd _agenttree/
git pull origin main

ISSUE_DIR=$(find issues/ -name "$ISSUE_NUM-*" -type d)

# Update issue.yaml
# (use yq or Python script to update YAML)
python3 -c "
import yaml
with open('$ISSUE_DIR/issue.yaml') as f:
    data = yaml.safe_load(f)
data['stage'] = '$NEW_STAGE'
data['updated_at'] = '$(date -Iseconds)'
with open('$ISSUE_DIR/issue.yaml', 'w') as f:
    yaml.dump(data, f)
"

git add "$ISSUE_DIR/issue.yaml"
git commit -m "Move issue #$ISSUE_NUM to stage $NEW_STAGE"
git push origin main

echo "Moved to stage: $NEW_STAGE"
```

### scripts/edit-issue.sh

```bash
#!/bin/bash
# Edit an issue document (pull, edit, push)

ISSUE_NUM=$1
DOC=$2  # e.g., "problem.md" or "plan.md"

cd _agenttree/
git pull origin main

ISSUE_DIR=$(find issues/ -name "$ISSUE_NUM-*" -type d)

# Open editor
${EDITOR:-vim} "$ISSUE_DIR/$DOC"

git add "$ISSUE_DIR/$DOC"
git commit -m "Update issue #$ISSUE_NUM: $DOC"
git push origin main

echo "Updated $DOC"
```

---

## CI Scripts (Local Enforcement)

### scripts/quick_ci.sh

```bash
#!/bin/bash
# Fast checks: lint, format, type check

set -e

echo "Running quick CI checks..."

# Check if configured
if ! command -v ruff &> /dev/null; then
    echo "❌ quick_ci.sh not configured!"
    echo ""
    echo "Install linting tools:"
    echo "  pip install ruff mypy"
    echo ""
    echo "Or customize this script for your project."
    echo "See: https://docs.agenttree.dev/ci-setup"
    exit 1
fi

echo "→ Running ruff (lint)..."
ruff check .

echo "→ Running ruff (format check)..."
ruff format --check .

echo "→ Running mypy (type check)..."
mypy src/

echo "✅ Quick CI passed!"
```

### scripts/ci.sh

```bash
#!/bin/bash
# Standard CI: run test suite

set -e

echo "Running CI (tests)..."

# Check if configured
if [ ! -f "pyproject.toml" ] && [ ! -f "pytest.ini" ]; then
    echo "❌ ci.sh not configured!"
    echo ""
    echo "Setup pytest for your project:"
    echo "  pip install pytest"
    echo "  pytest tests/"
    echo ""
    echo "See: https://docs.agenttree.dev/ci-setup"
    exit 1
fi

echo "→ Running pytest..."
pytest tests/ -v

echo "✅ CI passed!"
```

### scripts/extensive_ci.sh

```bash
#!/bin/bash
# Extensive CI: integration tests, e2e, etc.

set -e

echo "Running extensive CI..."

# Check if configured
if [ ! -d "tests/integration" ]; then
    echo "❌ extensive_ci.sh not configured!"
    echo ""
    echo "Create integration tests in tests/integration/"
    echo "See: https://docs.agenttree.dev/ci-setup"
    exit 1
fi

echo "→ Running integration tests..."
pytest tests/integration/ -v

echo "→ Running e2e tests..."
pytest tests/e2e/ -v

echo "✅ Extensive CI passed!"
```

---

## Stage-Specific Skills

Each stage loads different instructions/tools for the agent.

### _agenttree/skills/1-problem/understand-problem.md

```markdown
# Skill: Understand the Problem

**Stage:** Problem (1)
**Goal:** Write a clear problem statement that captures what needs to be solved

## Your Task

Read the issue description and create a `problem.md` document that answers:

1. **What is broken or missing?**
2. **Who is affected?**
3. **What is the expected behavior?**
4. **What is the current behavior?**
5. **What are the acceptance criteria?**

## Tools Available

- Read issue.yaml for context
- Explore codebase to understand current state
- Ask clarifying questions (add to problem.md as "Questions:")

## Output

Create `problem.md` in your issue directory:

```markdown
# Problem Statement

## What is broken?
[Describe the problem]

## Who is affected?
[Users, developers, specific features]

## Expected behavior
[What should happen]

## Current behavior
[What actually happens]

## Acceptance Criteria
- [ ] Criterion 1
- [ ] Criterion 2

## Questions
- Question 1?
- Question 2?
```

## When Done

Run: `agenttree next-stage` to move to Problem Review
```

### _agenttree/skills/5-implement/tdd-workflow.md

```markdown
# Skill: TDD Implementation

**Stage:** Implement (5)
**Goal:** Build the solution using test-driven development

## Your Task

Follow TDD cycle for each feature:

1. **Write failing test** (5b)
2. **Make test pass** (5c)
3. **Refactor** (5e)
4. **Repeat**

## Sub-Stages

### 5a: Setup Branch
```bash
git checkout -b issue-042
```

### 5b: Write Failing Test
- Write ONE test that captures the requirement
- Run test, verify it fails
- Commit: `git commit -m "Add failing test for X"`

### 5c: Implement Solution
- Write minimal code to make test pass
- Run test, verify it passes
- Commit: `git commit -m "Implement X"`

### 5d: Add Edge Cases
- Add tests for edge cases
- Implement handling
- Commit each

### 5e: Refactor
- Clean up code
- Remove duplication
- Improve names
- Commit: `git commit -m "Refactor X"`

### 5f: Document
- Add docstrings
- Update README if needed
- Add code comments for complex logic
- Commit: `git commit -m "Document X"`

## CI Enforcement

Before moving to next stage:
```bash
./scripts/quick_ci.sh  # Must pass
./scripts/ci.sh        # Must pass
```

## Output

Update `commit-log.md`:

```markdown
# Implementation Log

## Commits
- abc1234 Add failing test for login validation
- def5678 Implement login validation
- ghi9012 Add edge case for empty password
- jkl3456 Refactor validation logic
- mno7890 Document validation function

## Files Changed
- src/auth/login.py
- tests/test_login.py

## Notes
- Used bcrypt for password hashing
- Added rate limiting (5 attempts per minute)
```

## When Done

Run: `agenttree next-stage` to move to Implementation Review
```

---

## Claude Review API Integration

Replace PR reviews with direct API calls.

### scripts/review-issue.sh

```bash
#!/bin/bash
# Get code review from Claude API

ISSUE_NUM=$1

cd _agenttree/
ISSUE_DIR=$(find issues/ -name "$ISSUE_NUM-*" -type d)

# Get diff
cd ../../  # Back to main repo
DIFF=$(git diff main...$(git rev-parse --abbrev-ref HEAD))

# Call Claude API for review
python3 << EOF
import anthropic
import os

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

diff = """$DIFF"""

response = client.messages.create(
    model="claude-sonnet-4-20250514",
    max_tokens=4096,
    messages=[{
        "role": "user",
        "content": f"""Review this code diff and provide feedback:

{diff}

Focus on:
- Correctness and edge cases
- Code quality and maintainability
- Test coverage
- Security issues
- Performance concerns

Format as markdown with specific line references."""
    }]
)

review = response.content[0].text

# Save to review.md
with open("_agenttree/$ISSUE_DIR/review.md", "w") as f:
    f.write("# Code Review\n\n")
    f.write(review)

print(review)
EOF

# Commit review
cd _agenttree/
git add "$ISSUE_DIR/review.md"
git commit -m "Add Claude review for issue #$ISSUE_NUM"
git push origin main

echo "Review saved to $ISSUE_DIR/review.md"
```

---

## Implementation Plan

### Phase 1: Repository Setup (Week 1)

**Tasks:**
- [ ] Create _agenttree/ git repository
- [ ] Setup directory structure (issues/, templates/, scripts/, skills/)
- [ ] Create helper scripts (new-issue.sh, move-stage.sh, edit-issue.sh)
- [ ] Write stage templates (problem.md, plan.md, review.md)
- [ ] Write skills for each stage

**CLI commands:**
```bash
agenttree init-agents-repo     # Creates _agenttree/ repo
agenttree new-issue "title"    # Wraps scripts/new-issue.sh
agenttree move-stage 42 3      # Wraps scripts/move-stage.sh
```

### Phase 2: Kanban Web UI (Week 2)

**Backend:**
- [ ] Add FastAPI endpoints:
  - `GET /api/issues` - List all issues
  - `GET /api/issues/{id}` - Get issue detail
  - `POST /api/issues/{id}/move` - Move to stage
  - `PUT /api/issues/{id}/docs/{doc}` - Update document
  - `POST /api/issues/{id}/review` - Trigger Claude review

- [ ] Add state sync: Pull _agenttree/ repo before each request

**Frontend:**
- [ ] Create kanban.html template
- [ ] Implement drag-drop with HTMX + minimal JS
- [ ] Create issue modal with doc viewer/editor
- [ ] Add markdown rendering

### Phase 3: CI Scripts (Week 3)

**Tasks:**
- [ ] Create default CI scripts with helpful errors
- [ ] Add CI enforcement in move-stage.sh
- [ ] Document CI setup in docs

**Scripts:**
- quick_ci.sh - Template with error message
- ci.sh - Template with error message
- extensive_ci.sh - Template with error message

### Phase 4: Claude Review Integration (Week 4)

**Tasks:**
- [ ] Create review-issue.sh script
- [ ] Integrate with Claude API
- [ ] Add review enforcement in stage 6
- [ ] Add review.md template

### Phase 5: One Agent Per Task (Week 5)

**Refactor:**
- [ ] Remove task switching logic
- [ ] Simplify dispatch: one issue → one agent → done
- [ ] Update agent status to reflect issue stage
- [ ] Free agent when issue moves to "Accepted"

**Commands:**
```bash
agenttree assign <agent_num> <issue_num>
# - Creates issue dir in _agenttree/
# - Creates worktree for agent
# - Starts agent with stage 1 skills
# - Agent works until completion
```

---

## Design Decisions

### 1. Why Separate Repo?

**Pros:**
- Full control over workflow and stages
- Rich markdown docs per issue
- No GitHub API limits
- Can build custom tooling
- Source of truth for all issue state

**Cons:**
- Need to sync if want GitHub visibility
- One more repo to manage

**Decision:** Use separate repo. Optionally sync to GitHub Issues for visibility, but _agenttree/ is source of truth.

### 2. Why One Agent Per Task?

**Pros:**
- Simpler: no task switching
- Clearer: agent state = issue state
- Faster: no context switching overhead
- Easier to reason about

**Cons:**
- More agents needed for parallel work

**Decision:** One agent per task. Agents are cheap (just worktrees), simplicity is worth it.

### 3. Why Local CI?

**Pros:**
- Fast feedback (no waiting for GitHub Actions)
- Catches issues before push
- Enforces quality at stage transitions
- No CI minutes consumed

**Cons:**
- Requires local setup
- Can't test on multiple platforms

**Decision:** Local CI enforcement. Optionally run GitHub Actions for multi-platform testing, but don't block on it.

### 4. Why Claude Review API?

**Pros:**
- Instant feedback (no PR delay)
- Programmable (can enforce checks)
- Part of the workflow, not separate
- Faster iteration

**Cons:**
- Costs API tokens
- Can't replace human review

**Decision:** Use Claude for automated review. Still allow human review, but don't require it for every issue.

---

## Example: Issue Lifecycle

### 1. Create Issue

```bash
agenttree new-issue "fix-login-bug" "Login fails with empty password"
# Creates: _agenttree/issues/042-fix-login-bug/issue.yaml
# Stage: backlog
```

### 2. Assign to Agent

```bash
agenttree assign 1 42
# - Moves issue to stage 1 (Problem)
# - Creates worktree for agent-1
# - Loads problem-understanding skill
# - Starts Claude in tmux
```

### 3. Agent Works Through Stages

**Stage 1: Problem**
- Agent reads issue
- Explores codebase
- Writes problem.md
- Runs: `agenttree next-stage`

**Stage 2: Problem Review**
- User reviews problem.md in kanban UI
- Drags to "Plan" stage (or gives feedback)

**Stage 3: Research/Plan**
- Agent explores codebase
- Designs solution
- Writes plan.md
- Runs: `agenttree next-stage`

**Stage 4: Plan Review**
- User reviews plan.md
- Approves → drags to "Implement"

**Stage 5: Implement**
- Agent follows TDD workflow
- Writes tests → implements → refactors
- Runs quick_ci.sh and ci.sh
- Updates commit-log.md
- Runs: `agenttree next-stage`

**Stage 6: Implementation Review**
- Agent runs: `agenttree review 42` (Claude API)
- Reviews review.md feedback
- Addresses issues
- Runs extensive_ci.sh
- Runs: `agenttree next-stage`

**Stage 7: Accepted**
- Issue complete!
- Agent worktree freed
- Issue moved to _agenttree/issues/archive/

---

## FAQ

**Q: Do we still use GitHub Issues?**
A: Optional. You can sync _agenttree/ issues to GitHub for visibility, or just use _agenttree/ as single source of truth.

**Q: What if multiple people work on the codebase?**
A: _agenttree/ repo syncs like any git repo. Pull before editing, push after. Helper scripts do this automatically.

**Q: How do we handle merge conflicts in _agenttree/?**
A: Rare (each issue in own dir). If it happens, resolve like normal git conflict.

**Q: Can users edit issues directly in web UI?**
A: Yes! Modal has edit button → calls backend → backend pulls, updates, pushes.

**Q: What about GitHub PRs?**
A: Still create PRs for code changes. But review happens via Claude API first, PR is just for merging.

**Q: How do we track time spent?**
A: issue.yaml has timestamps. Can add time tracking fields if needed.

---

## Next Steps

1. **Review this plan** - Does it address your needs?
2. **Decide on repo name** - _agenttree/ or something else?
3. **Start Phase 1** - Setup repository structure
4. **Build kanban UI** - Start with static HTML, add interactivity
5. **Test with one issue** - Walk through full lifecycle

---

## References

- Django Riff SPA: https://thingsilearned.com/things/django-riff-spa/
- Claude Code: https://docs.anthropic.com/claude-code
- HTMX: https://htmx.org/
- FastAPI: https://fastapi.tiangolo.com/
