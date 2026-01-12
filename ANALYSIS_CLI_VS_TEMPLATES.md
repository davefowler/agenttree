# Analysis: CLI Tools vs Templates for Agent Documentation

**Date:** 2026-01-04
**Question:** Should agents manually create docs from templates, or should we provide CLI tools that auto-populate frontmatter?

## Current State

### Already Auto-Created by CLI ✓

1. **Task logs** - `agents/tasks/agent-{N}/{date}-{slug}.md`
   - Created by: `agenttree dispatch`
   - Auto-populated: agent, issue, timestamps, git context
   - Agent action: Fill in work log section

2. **Spec files** - `agents/specs/features/issue-{N}.md`
   - Created by: `agenttree dispatch`
   - Auto-populated: issue title, description, URL
   - Agent action: Add implementation notes

3. **Templates** - `agents/templates/*.md`
   - Created by: `agenttree init`
   - Purpose: Reference templates for agents

### Currently Manual (Agent Creates)

1. **Notes** - `agents/notes/agent-{N}/{topic}.md`
   - Agent copies template or creates from scratch
   - Must manually fill frontmatter
   - Risk: Inconsistent format, missing fields

2. **RFCs** - `agents/rfcs/{number}-{slug}.md`
   - Agent copies template
   - Must manually number, fill frontmatter
   - Risk: RFC numbering conflicts

3. **Investigations** - `agents/investigations/{date}-{slug}.md`
   - Agent creates manually
   - Must fill all frontmatter fields
   - Risk: Forgetting important metadata

4. **Context summaries** - `agents/context/agent-{N}/issue-{N}.md`
   - Currently not created (from PLAN_TASK_REENGAGEMENT.md)
   - Should be auto-created on task completion

---

## The Problem: Manual Templates Are Error-Prone

**Example: Agent creating a note manually**

Agent thinks: "I'll document this JWT pattern I discovered"

```bash
# Agent tries to remember template format
cat > agents/notes/agent-1/jwt-pattern.md <<EOF
---
document_type: note
# Wait, what other fields do I need?
# Let me check the template...
# *Opens templates/note.md*
# Oh, I need version, title, author, created_at, note_type...
# What format for created_at? ISO 8601? UTC?
# What's my agent number again? Let me check .env...
---
```

**Problems:**
- Cognitive load (agent must remember schema)
- Time wasted looking up format
- Typos in field names (`created_at` vs `createdAt`)
- Wrong timestamp format
- Forgetting optional-but-useful fields
- Inconsistent frontmatter across agents

---

## Solution 1: Keep Templates (Status Quo)

**How it works:**
- Agents copy from `agents/templates/`
- Fill in frontmatter manually
- Hope they get it right

**Pros:**
- ✅ Simple (no new code)
- ✅ Flexible (agents can customize)
- ✅ No CLI to learn

**Cons:**
- ❌ Error-prone (typos, wrong format)
- ❌ Inconsistent (each agent might format differently)
- ❌ Missing fields (agents forget optional metadata)
- ❌ High cognitive load (must remember schema)
- ❌ Hard to validate (no enforcement)

**Verdict:** ⚠️ Works for simple cases, but quality degrades over time

---

## Solution 2: CLI Tools (Auto-Populate Everything)

**How it works:**
```bash
# Instead of manual template copying:
agenttree create-note "JWT Refresh Pattern" \
  --type gotcha \
  --tags auth,security,jwt \
  --applies-to src/auth/jwt.ts
```

**CLI auto-populates:**
- `document_type: note`
- `version: 1`
- `author: agent-1` (from $AGENT_NUM)
- `created_at: 2026-01-04T10:30:00Z` (UTC now)
- `discovered_in_task: tasks/agent-1/2026-01-04-fix-auth.md` (current task)
- `note_type: gotcha` (from --type flag)
- `tags: [auth, security, jwt]`
- Git context (repo_url, current_commit)

**Agent writes:**
Just the markdown content! CLI opens editor with template:

```markdown
---
document_type: note
version: 1
note_type: gotcha
title: "JWT Refresh Pattern"
author: agent-1
created_at: 2026-01-04T10:30:00Z
updated_at: 2026-01-04T10:30:00Z
discovered_in_task: tasks/agent-1/2026-01-04-fix-auth.md
issue_number: 42
applies_to_files:
  - src/auth/jwt.ts
severity: important
tags:
  - auth
  - security
  - jwt
related_notes: []
related_specs: []
repo_url: https://github.com/user/project
---

# JWT Refresh Pattern

<!-- Agent writes content here -->
```

**Pros:**
- ✅ Consistent format (enforced by CLI)
- ✅ No typos in field names
- ✅ Auto-populated metadata (less to remember)
- ✅ Validated schema
- ✅ Git context automatically included
- ✅ Low cognitive load (just write content)

**Cons:**
- ❌ More code to maintain
- ❌ Agents must learn CLI commands
- ❌ Less flexible (locked into schema)
- ❌ Requires CLI access (not just git repo)

**Verdict:** ✅ Better quality, more maintainable long-term

---

## Solution 3: Hybrid (Best of Both)

**How it works:**
- **Structured docs** (RFCs, investigations) → CLI tools (required)
- **Simple notes** → Templates okay, but validated on commit
- **Auto-created docs** (task logs, specs, context) → CLI (already done)

### Tier 1: Always Auto-Created (Already Implemented)

```bash
# Task logs - auto-created on dispatch
agenttree dispatch 1 42
# Creates: agents/tasks/agent-1/2026-01-04-fix-auth.md
# All frontmatter auto-populated

# Spec files - auto-created on dispatch
agenttree dispatch 1 42
# Creates: agents/specs/features/issue-42.md
# All frontmatter auto-populated
```

**Status:** ✅ Already working

---

### Tier 2: CLI Tools for Structured Docs (New)

**Why:** These docs have complex schemas, sequential numbering, or critical metadata

#### RFC Creation

```bash
agenttree create-rfc "Implement JWT Authentication" \
  --author agent-1 \
  --related-issue 42
```

**Auto-populates:**
- RFC number (scans `agents/rfcs/`, picks next number)
- Frontmatter (document_type, version, author, proposed_at)
- Git context
- Template structure

**Agent writes:**
- Summary
- Motivation
- Detailed design
- Alternatives

**Benefits:**
- ✅ No RFC numbering conflicts
- ✅ Consistent format
- ✅ All metadata captured

---

#### Investigation Creation

```bash
agenttree create-investigation "Session store race condition" \
  --issue 45 \
  --severity critical
```

**Auto-populates:**
- Title, investigator, started_at
- Issue context (if --issue provided)
- Git context
- Severity
- Template structure

**Agent fills in:**
- Problem description
- Investigation steps
- Root cause
- Solution

**Benefits:**
- ✅ No forgetting severity/issue number
- ✅ Timestamps accurate
- ✅ Git context preserved

---

### Tier 3: Simple Notes (Templates + Validation)

**Why:** Notes are informal, agents should write freely

**Agent creates note** (either method):

**Method 1: Template** (flexible)
```bash
cp agents/templates/note.md agents/notes/agent-1/my-note.md
# Edit manually
```

**Method 2: CLI helper** (easier)
```bash
agenttree create-note "Token expiry gotcha" --type gotcha
# Opens editor with pre-filled frontmatter
```

**Validation on commit:**
```bash
# When agent commits to agents/ repo:
git commit -m "Add note on token expiry"

# Git hook runs:
agenttree validate-frontmatter agents/notes/agent-1/my-note.md
# ✓ Valid frontmatter
# ✓ All required fields present
# ✓ Timestamps in correct format
```

**Benefits:**
- ✅ Flexibility (can use template or CLI)
- ✅ Quality guaranteed (validated before commit)
- ✅ Catches errors early (pre-commit hook)

---

### Tier 4: Auto-Created on Events (New)

**Context summaries** - Created on task completion:

```bash
# When task completes:
agenttree complete 1 --pr 50

# CLI prompts:
# "Create context summary? [Y/n]"
# Opens editor with pre-filled template:
```

```markdown
---
document_type: context_summary
version: 1
task_id: agent-1-2026-01-04-fix-auth-bug
issue_number: 42
agent: agent-1
task_started: 2026-01-04T10:30:00Z
summary_created: 2026-01-04T15:45:00Z
repo_url: https://github.com/user/project
work_branch: agent-1/fix-auth-bug
final_commit: abc123def456
pr_number: 50
pr_status: open
commits_count: 5
files_changed_count: 8
key_files:
  - src/auth/jwt.ts
  - src/api/client.ts
  - tests/auth.test.ts
task_log: tasks/agent-1/2026-01-04-fix-auth.md
spec_file: specs/features/issue-42.md
tags: [authentication, jwt, security]
---

# Context Summary: Fix authentication bug

## What Was Done

<!-- Agent fills this in -->

## Key Decisions

<!-- Agent fills this in -->

## Gotchas Discovered

<!-- Agent fills this in -->

## For Resuming

<!-- Agent fills this in -->
```

**Benefits:**
- ✅ Never forget to create context summary
- ✅ Git metadata captured at right moment
- ✅ Integrates with task completion workflow

---

## Recommended Approach: Hybrid

### Phase 1: Add CLI Tools for Structured Docs

**New commands:**

```bash
agenttree create-rfc TITLE [OPTIONS]
  --author AGENT_NUM       # Default: $AGENT_NUM
  --related-issue NUM
  --complexity high|medium|low

agenttree create-investigation TITLE [OPTIONS]
  --issue NUM
  --severity critical|high|medium|low
  --affected-files FILE1,FILE2

agenttree create-note TITLE [OPTIONS]
  --type gotcha|pattern|tip|question
  --tags TAG1,TAG2
  --applies-to FILE
  --severity important|nice_to_know

agenttree complete AGENT_NUM [OPTIONS]
  --pr PR_NUM
  --create-summary          # Force create context summary
  --skip-summary            # Skip context summary
```

**Default behavior:**
- Auto-detect agent from $AGENT_NUM
- Auto-populate timestamps (UTC)
- Auto-populate git context
- Open editor for content
- Validate frontmatter before saving
- Auto-commit to agents/ repo (optional)

---

### Phase 2: Add Frontmatter Validation

**Git hook** (agents/.git/hooks/pre-commit):

```bash
#!/bin/bash
# Validate all markdown files being committed

for file in $(git diff --cached --name-only | grep '\.md$'); do
  agenttree validate-frontmatter "$file"
  if [ $? -ne 0 ]; then
    echo "❌ Invalid frontmatter in $file"
    echo "Fix errors or use: agenttree fix-frontmatter $file"
    exit 1
  fi
done
```

**Validation checks:**
- ✓ YAML syntax valid
- ✓ Required fields present
- ✓ Field types correct (string, list, int)
- ✓ Timestamps in ISO 8601 format
- ✓ document_type is valid enum
- ✓ version field present

**Helper command:**
```bash
agenttree fix-frontmatter agents/notes/agent-1/my-note.md
# Auto-fixes common issues:
# - Adds missing required fields
# - Fixes timestamp format
# - Adds version field
# - Validates enums
```

---

### Phase 3: Integration with AGENT_GUIDE.md

Update agent guide to recommend CLI tools:

```markdown
## Creating Documentation

### Quick Notes

Use the CLI for consistent formatting:

$ agenttree create-note "JWT token validation edge case" \
  --type gotcha \
  --tags auth,security

This auto-populates all metadata. Just write your content!

### Design Proposals

$ agenttree create-rfc "Add OAuth2 support"

Creates RFC with next available number.

### Bug Investigations

$ agenttree create-investigation "Race condition in session store" \
  --issue 45 \
  --severity critical

Captures git context at start of investigation.

### Manual Templates (Advanced)

If you prefer manual control:
1. Copy template: `cp agents/templates/note.md agents/notes/agent-1/my-note.md`
2. Edit frontmatter
3. Commit (validation hook will check format)
```

---

## Implementation Plan

### Week 1: Core CLI Tools

**Files to create:**
- `agenttree/cli_docs.py` - Document creation commands
- `agenttree/frontmatter.py` - Frontmatter utilities (already planned)
- `agenttree/validators.py` - Frontmatter validation

**Commands to implement:**
```python
@main.group()
def docs():
    """Create and manage agent documentation."""
    pass

@docs.command("create-note")
@click.argument("title")
@click.option("--type", type=click.Choice(["gotcha", "pattern", "tip", "question"]))
@click.option("--tags", help="Comma-separated tags")
@click.option("--applies-to", help="File this note applies to")
@click.option("--severity", type=click.Choice(["important", "nice_to_know"]))
def create_note(title, type, tags, applies_to, severity):
    """Create a new note with auto-populated frontmatter."""
    # Auto-populate frontmatter
    # Open editor
    # Validate
    # Save to agents/notes/agent-{N}/

@docs.command("create-rfc")
@click.argument("title")
@click.option("--related-issue", type=int)
def create_rfc(title, related_issue):
    """Create a new RFC with auto-numbered sequence."""
    # Scan agents/rfcs/ for next number
    # Auto-populate frontmatter
    # Open editor
    # Save

@docs.command("create-investigation")
@click.argument("title")
@click.option("--issue", type=int)
@click.option("--severity", type=click.Choice(["critical", "high", "medium", "low"]))
def create_investigation(title, issue, severity):
    """Create investigation document."""
    # Auto-populate frontmatter
    # Open editor
    # Save
```

---

### Week 2: Validation

**Commands:**
```python
@docs.command("validate")
@click.argument("file_path")
def validate_frontmatter(file_path):
    """Validate frontmatter in a markdown file."""
    # Parse frontmatter
    # Check schema
    # Report errors

@docs.command("fix")
@click.argument("file_path")
def fix_frontmatter(file_path):
    """Auto-fix common frontmatter issues."""
    # Parse file
    # Add missing required fields
    # Fix timestamp format
    # Write back
```

**Git hook setup:**
```python
@docs.command("install-hooks")
def install_hooks():
    """Install git hooks for frontmatter validation."""
    # Copy pre-commit hook to agents/.git/hooks/
    # Make executable
```

---

### Week 3: Task Completion Integration

**Enhance `agenttree dispatch` and add `agenttree complete`:**

```python
@main.command()
@click.argument("agent_num", type=int)
@click.option("--pr", type=int, help="PR number created")
@click.option("--create-summary/--skip-summary", default=True)
def complete(agent_num, pr, create_summary):
    """Mark task as complete and optionally create context summary."""
    # Load current task
    # Get git context (commits made, files changed)
    # Update task log frontmatter with PR, completion time

    if create_summary:
        # Auto-create context summary with pre-filled frontmatter
        # Open editor for agent to fill in
        # Save to agents/context/
```

---

## Comparison: Manual vs CLI

### Scenario: Agent wants to document a gotcha

**Manual Template Approach:**

```bash
# Step 1: Find template
cd agents/templates
cat note.md

# Step 2: Copy template
cp note.md ../notes/agent-1/jwt-token-gotcha.md

# Step 3: Open editor
vim ../notes/agent-1/jwt-token-gotcha.md

# Step 4: Fill frontmatter manually
# - Check what my agent number is
# - Format current timestamp in ISO 8601
# - Look up repo URL
# - Get current commit hash
# - Remember to add tags
# - Hope I didn't typo anything

# Step 5: Write content

# Step 6: Commit
git add .
git commit -m "Add note on JWT gotcha"

# Total time: ~5 minutes
# Error risk: HIGH
```

**CLI Tool Approach:**

```bash
# Step 1: Run command
agenttree create-note "JWT token expiry gotcha" \
  --type gotcha \
  --tags auth,jwt \
  --applies-to src/auth/jwt.ts \
  --severity important

# Editor opens with pre-filled frontmatter:
# ---
# document_type: note
# version: 1
# note_type: gotcha
# title: "JWT token expiry gotcha"
# author: agent-1
# created_at: 2026-01-04T10:30:00Z
# ...all other fields auto-populated...
# ---

# Step 2: Write content

# Step 3: Save and exit

# CLI auto-commits (optional)
# Or: git commit -m "Add note on JWT gotcha"

# Total time: ~1 minute
# Error risk: LOW
```

**Savings:**
- ⏱️ 4 minutes saved per doc
- 🎯 Zero typos in frontmatter
- ✅ Consistent format
- 🧠 Lower cognitive load

**Over 100 docs:** 400 minutes saved = 6.7 hours

---

## Decision Matrix

| Document Type | Frequency | Complexity | Recommendation | Reason |
|--------------|-----------|------------|----------------|---------|
| Task logs | High | Medium | ✅ CLI (done) | Auto-created on dispatch |
| Spec files | High | Medium | ✅ CLI (done) | Auto-created on dispatch |
| Context summaries | High | High | ✅ CLI (new) | Critical for re-engagement |
| RFCs | Low | High | ✅ CLI (new) | Sequential numbering, complex schema |
| Investigations | Medium | High | ✅ CLI (new) | Critical metadata (severity, root cause) |
| Notes | High | Low | ⚖️ Template OR CLI | Agent choice, validated on commit |
| Knowledge files | Low | Low | ⚖️ Template | Rare updates, simple format |

**Legend:**
- ✅ CLI = Strong recommend CLI tool
- ⚖️ Template OR CLI = Either approach fine
- ❌ Manual = Keep template-based

---

## Recommendation: Hybrid with CLI Priority

### Implement CLI Tools For:

1. **RFC creation** (`agenttree create-rfc`)
   - Auto-number RFCs
   - Prevent numbering conflicts
   - Capture git context

2. **Investigation creation** (`agenttree create-investigation`)
   - Ensure severity is set
   - Link to issue automatically
   - Timestamp investigation start

3. **Note creation** (`agenttree create-note`)
   - Optional (agent can use template)
   - But recommended for consistency
   - Reduces errors

4. **Context summary creation** (`agenttree complete`)
   - Auto-created on task completion
   - Critical for task re-engagement
   - Must capture exact git state

### Keep Templates For:

1. **Reference** - Agents can still see schema
2. **Advanced customization** - Power users can override
3. **Backward compatibility** - Existing workflow still works

### Add Validation For:

1. **Pre-commit hook** - Validates all .md files
2. **CI check** - Fails if invalid frontmatter
3. **Manual check** - `agenttree validate agents/notes/my-note.md`

---

## Next Steps

1. **Review this analysis**
   - Do you agree with hybrid approach?
   - Any document types I missed?

2. **Prioritize implementation**
   - Start with `create-rfc` (most complex, highest value)?
   - Or `complete` (task re-engagement)?
   - Or `create-note` (highest frequency)?

3. **Define validation rules**
   - What fields are required vs optional?
   - How strict should validation be?

4. **Update AGENT_GUIDE.md**
   - Add section on using CLI tools
   - When to use template vs CLI

**My recommendation:** Start with Phase 1 CLI tools (Week 1), get feedback from real usage, then add validation.

Would you like me to implement the CLI tools, starting with `agenttree create-rfc` or `agenttree complete`?
