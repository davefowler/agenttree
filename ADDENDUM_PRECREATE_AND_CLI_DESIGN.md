# Addendum: Pre-Creation Pattern & CLI Design

**Date:** 2026-01-04
**Addendum to:** ANALYSIS_CLI_VS_TEMPLATES.md

## New Pattern: Pre-Create Documents

### The Insight

Instead of creating docs on-demand (template or CLI), **pre-create them during dispatch** with frontmatter already filled, then agents just edit.

**Example:**
```bash
agenttree start 1 42

# Creates ALL expected docs upfront:
# 1. TASK.md (current task)
# 2. _agenttree/tasks/agent-1/2026-01-04-issue-42.md (task log)
# 3. _agenttree/specs/features/issue-42.md (spec)
# 4. _agenttree/context/agent-1/issue-42.md (PRE-CREATED!) ← NEW
```

Context summary already exists with:
- All frontmatter filled (git context, issue, timestamps)
- Template sections (What Was Done, Key Decisions, Gotchas)
- Agent just fills in content during/after work

---

## Comparison: 3 Creation Patterns

### Pattern 1: Templates (Manual)

**When:** Agent copies template, fills everything
```bash
cp _agenttree/templates/context.md _agenttree/context/agent-1/issue-42.md
# Agent fills frontmatter + content
```

**Pros:** ✅ Flexible
**Cons:** ❌ Error-prone, time-consuming

---

### Pattern 2: CLI Tool (On-Demand)

**When:** Agent runs command when they need doc
```bash
agenttree create-context 42
# Auto-fills frontmatter, opens editor
```

**Pros:** ✅ Auto-populated, validated
**Cons:** ⚠️ Agent must remember to create it

---

### Pattern 3: Pre-Create (Automatic)

**When:** System creates during dispatch/setup
```bash
agenttree start 1 42
# Auto-creates context summary file (empty content)
```

**Pros:**
✅ Zero friction (already exists)
✅ Always created (won't forget)
✅ Frontmatter fully populated upfront
✅ Agent just fills content

**Cons:**
⚠️ Creates files that might not be needed
⚠️ Clutters filesystem if task abandoned
⚠️ Less flexible (what if agent doesn't want that doc?)

---

## Decision Matrix: Which Pattern for Which Doc?

| Document Type | Frequency | Criticality | Best Pattern | Rationale |
|--------------|-----------|-------------|--------------|-----------|
| **Task log** | 100% | Critical | ✅ Pre-create (done) | Always needed, already created on dispatch |
| **Spec file** | 100% | High | ✅ Pre-create (done) | Always created from issue |
| **Context summary** | 100% | Critical | ✅ **Pre-create** | ALWAYS needed for re-engagement |
| **RFC** | 5% | Medium | 🔧 CLI tool | Rare, only for major decisions |
| **Investigation** | 30% | Medium | 🔧 CLI tool | Sometimes needed, not always |
| **Notes** | 50% | Low | 📝 Template OR CLI | Ad-hoc, varies by agent |

**Legend:**
- ✅ Pre-create = Create automatically during dispatch
- 🔧 CLI tool = Agent creates on-demand via command
- 📝 Template OR CLI = Agent choice, both supported

---

## Recommended: Hybrid of All 3 Patterns

### Tier 1: Pre-Create (100% Needed)

**Documents:**
- Task logs (✓ already done)
- Spec files (✓ already done)
- Context summaries (NEW!)

**Implementation:**

```python
# In cli.py dispatch() function:
def dispatch(agent_num, issue_number, ...):
    # ... existing code to create TASK.md, task log, spec ...

    # NEW: Pre-create context summary
    context_file = agents_repo_path / "context" / f"agent-{agent_num}" / f"issue-{issue_number}.md"

    frontmatter = {
        "document_type": "context_summary",
        "version": 1,
        "task_id": f"agent-{agent_num}-{date}-{slug}",
        "issue_number": issue_number,
        "agent": f"agent-{agent_num}",
        "task_started": datetime.utcnow().isoformat() + "Z",
        "summary_created": None,  # Filled when agent completes
        "repo_url": get_repo_url(),
        "work_branch": f"agent-{agent_num}/...",
        "starting_commit": get_current_commit(),
        # ... more auto-filled fields
    }

    content = create_frontmatter(frontmatter)
    content += """# Context Summary: {issue_title}

## What Was Done

<!-- Fill this in as you work, or at task completion -->

## Key Decisions

<!-- Document important architectural/design decisions -->

## Gotchas Discovered

<!-- Any non-obvious issues you hit -->

## Key Files Modified

<!-- List main files changed with brief descriptions -->

## For Resuming

<!-- If someone (including you) needs to resume this task later, what should they know? -->
"""
    context_file.write_text(content)
```

**Agent workflow:**
```bash
# Day 1: Agent starts task
agenttree start 1 42

# File already exists: _agenttree/context/agent-1/issue-42.md
# Agent can update it as they work:
echo "
## What Was Done
- Fixed JWT validation logic
" >> _agenttree/context/agent-1/issue-42.md

# Day 3: Agent completes task
agenttree complete 1 --pr 50
# CLI updates frontmatter (summary_created, final_commit, pr_number)
# Prompts agent to review/finish context summary
# Agent edits, saves, done
```

**Benefits:**
- ✅ File exists from start (agent can update as they work)
- ✅ No "did I create context summary?" uncertainty
- ✅ Frontmatter pre-filled (git context captured at start)
- ✅ Agent just fills content sections
- ✅ `agenttree complete` updates remaining frontmatter fields

---

### Tier 2: CLI Tools (Sometimes Needed)

**Documents:**
- RFCs (rare, important)
- Investigations (sometimes)

**Why not pre-create:**
- Not every task needs an RFC
- Not every task is a bug investigation
- Would clutter filesystem with unused files

**Implementation:**
```bash
# Agent decides: "This needs a design doc"
agenttree create-rfc "Add OAuth2 support"

# Agent decides: "I need to investigate this bug"
agenttree create-investigation "Session race condition" --issue 45
```

---

### Tier 3: Flexible (Agent Choice)

**Documents:**
- Notes (informal, ad-hoc)

**Why flexible:**
- Varies by agent preference
- Some agents document heavily, others minimally
- Not critical (nice-to-have)

**Implementation:**
```bash
# Option A: Template (flexible)
cp _agenttree/templates/note.md _agenttree/notes/agent-1/my-note.md

# Option B: CLI (easier)
agenttree create-note "JWT pattern"

# Both work, git hook validates
```

---

## Question 2: CLI Design - One Tool vs Many Tools?

### User's Question:
> Should we have one tool with many --type options, or a new tool for each note type?

### Option A: Unified Tool with --type Flag

```bash
agenttree create-doc "Title" --type note
agenttree create-doc "Title" --type rfc
agenttree create-doc "Title" --type investigation
agenttree create-doc "Title" --type context
```

**Pros:**
- ✅ Single command to learn
- ✅ Consistent interface
- ✅ Less code duplication

**Cons:**
- ❌ Must remember valid --type values
- ❌ Generic help text (not type-specific)
- ❌ Type-specific options awkward (--severity for investigation only?)
- ❌ Error messages less helpful ("invalid type" vs "use create-rfc")

---

### Option B: Specialized Tools

```bash
agenttree create-note "Title"
agenttree create-rfc "Title"
agenttree create-investigation "Title"
```

**Pros:**
- ✅ Clear intent (tool name = what you're creating)
- ✅ Type-specific help text
- ✅ Type-specific options (--severity for investigation, --complexity for RFC)
- ✅ Better error messages
- ✅ Discoverable via tab completion

**Cons:**
- ❌ More commands to maintain
- ❌ Slight code duplication

---

### Option C: Namespaced Subcommands (Hybrid)

```bash
agenttree docs create-note "Title"
agenttree docs create-rfc "Title"
agenttree docs create-investigation "Title"
agenttree docs list
agenttree docs validate <file>
```

**Pros:**
- ✅ All doc operations under `docs.*` namespace
- ✅ Specialized commands (clear intent)
- ✅ Organized (`agenttree docs --help` shows all)
- ✅ Extensible (add more subcommands easily)

**Cons:**
- ⚠️ Slightly longer commands
- ⚠️ Must remember `docs` prefix

---

## What Works Better for AI Agents?

**Recommendation: Option B (Specialized Tools)** or **Option C (Namespaced)**

### Why Specialized Tools Win for AI Agents:

#### 1. **Clearer Intent = Better Tool Selection**

Agent thinks: "I need to document this design decision"

**Option A (unified):**
```
Hmm, is it create-doc --type rfc? Or --type design? Let me check help...
```

**Option B (specialized):**
```
Oh, create-rfc! That's exactly what I need.
```

---

#### 2. **Better Help Text = Faster Learning**

**Option A:**
```bash
$ agenttree create-doc --help
Create a document.

Options:
  --type [note|rfc|investigation|...]  Document type
  --tags TEXT                          Tags (comma-separated)
  --severity [critical|high|low]       Severity (investigation only)
  --complexity [high|low]              Complexity (RFC only)
  ...
```
Confusing! Which options apply to which types?

**Option B:**
```bash
$ agenttree create-rfc --help
Create an RFC (Request for Comments) design proposal.

Options:
  --related-issue INT    Related GitHub issue number
  --complexity [high|medium|low]

Examples:
  agenttree create-rfc "Add OAuth2 support" --related-issue 42
```
Clear! Shows exactly what's available for RFCs.

---

#### 3. **Type-Specific Options = Better UX**

**Option A (unified):**
```bash
# For investigation:
agenttree create-doc "Race condition" --type investigation --severity critical

# For RFC:
agenttree create-doc "OAuth2" --type rfc --complexity high

# For note:
agenttree create-doc "JWT pattern" --type note
```
Same command, different options. Agent must know which options apply.

**Option B (specialized):**
```bash
# Investigation has --severity
agenttree create-investigation "Race condition" --severity critical

# RFC has --complexity
agenttree create-rfc "OAuth2" --complexity high

# Note has simple interface
agenttree create-note "JWT pattern"
```
Each tool has exactly the options it needs. No confusion.

---

#### 4. **Discoverability via Tab Completion**

**Option A:**
```bash
$ agenttree create-<TAB>
create-doc
```
One option. Must then figure out --type values.

**Option B:**
```bash
$ agenttree create-<TAB>
create-note          create-rfc          create-investigation
create-context       ...
```
All options visible! Agent can discover what's available.

---

#### 5. **Better Error Messages**

**Option A:**
```bash
$ agenttree create-doc "Title" --type rfc --severity critical
Error: --severity is not valid for type 'rfc'
```
Generic error. Agent must figure out which options apply to which types.

**Option B:**
```bash
$ agenttree create-rfc "Title" --severity critical
Error: No such option: --severity
Did you mean: create-investigation?
```
Specific error with helpful suggestion!

---

## Real-World Example: Git vs Subversion

**Subversion (unified):**
```bash
svn commit --type update
svn commit --type add
svn commit --type delete
```
(Not how it works, but similar pattern)

**Git (specialized):**
```bash
git commit
git add
git rm
git mv
```
Specialized commands. Clear intent. Industry standard.

**Git won** partly because of this design!

---

## Recommendation for AgentTree

### Use **Option B (Specialized Tools)** or **Option C (Namespaced)**

**Immediate (Week 1):**

**Top-level commands** (most common):
```bash
agenttree create-note "Title"        # Frequent
agenttree create-rfc "Title"         # Important
agenttree create-investigation "Title"  # Sometimes
```

**Namespace for management** (less common):
```bash
agenttree docs list                  # Browse all docs
agenttree docs validate <file>       # Check frontmatter
agenttree docs fix <file>            # Auto-fix issues
```

**Rationale:**
- Common creation commands at top level (shorter, easier)
- Management commands under namespace (organized)
- Best of both worlds

---

## Updated Recommendation

### Pattern 1: Pre-Create (100% Needed)

```python
# In dispatch():
- Create TASK.md (✓ done)
- Create task log (✓ done)
- Create spec file (✓ done)
- Create context summary (NEW!)
```

Context summary pre-created with:
- All frontmatter filled
- Template sections for agent to fill
- Agent updates as they work
- `agenttree complete` finalizes it

---

### Pattern 2: CLI Tools (Sometimes Needed)

**Specialized commands:**
```bash
agenttree create-rfc "Title" [options]
agenttree create-investigation "Title" [options]
agenttree create-note "Title" [options]
```

Each with type-specific options and help.

---

### Pattern 3: Management Commands

**Namespaced:**
```bash
agenttree docs list [--type TYPE] [--agent NUM]
agenttree docs validate <file>
agenttree docs fix <file>
agenttree docs search <query>
```

---

## Implementation Example

**Specialized tools with shared base:**

```python
# agenttree/cli_docs.py

from agenttree.frontmatter import create_frontmatter, get_git_context
from agenttree.doc_schemas import NOTE_SCHEMA, RFC_SCHEMA, INVESTIGATION_SCHEMA

def _create_doc(doc_type: str, title: str, schema: dict, extra_fields: dict):
    """Shared doc creation logic."""
    # Auto-populate common fields
    git_ctx = get_git_context()
    agent_num = os.getenv("AGENT_NUM")

    frontmatter = {
        "document_type": doc_type,
        "version": 1,
        "title": title,
        "author": f"agent-{agent_num}",
        "created_at": datetime.utcnow().isoformat() + "Z",
        **git_ctx,
        **extra_fields
    }

    # Validate against schema
    validate_frontmatter(frontmatter, schema)

    # Create file
    content = create_frontmatter(frontmatter)
    content += get_template(doc_type)

    # Open editor
    open_editor(filepath, content)

@main.command("create-note")
@click.argument("title")
@click.option("--type", type=click.Choice(["gotcha", "pattern", "tip", "question"]))
@click.option("--tags", help="Comma-separated tags")
@click.option("--applies-to", help="File this note applies to")
def create_note(title, type, tags, applies_to):
    """Create a note with auto-populated frontmatter.

    Examples:
        agenttree create-note "JWT token expiry gotcha" --type gotcha
        agenttree create-note "API retry pattern" --type pattern --tags api,resilience
    """
    extra = {
        "note_type": type,
        "tags": tags.split(",") if tags else [],
        "applies_to_files": [applies_to] if applies_to else []
    }
    _create_doc("note", title, NOTE_SCHEMA, extra)

@main.command("create-rfc")
@click.argument("title")
@click.option("--related-issue", type=int)
@click.option("--complexity", type=click.Choice(["high", "medium", "low"]))
def create_rfc(title, related_issue, complexity):
    """Create an RFC (Request for Comments) design proposal.

    RFCs are automatically numbered (scans existing RFCs for next number).

    Examples:
        agenttree create-rfc "Add OAuth2 support" --related-issue 42
        agenttree create-rfc "Redesign database schema" --complexity high
    """
    # Auto-number RFC
    rfc_number = get_next_rfc_number()

    extra = {
        "rfc_number": rfc_number,
        "related_issue": related_issue,
        "complexity": complexity,
        "status": "proposed"
    }
    _create_doc("rfc", title, RFC_SCHEMA, extra)

@main.command("create-investigation")
@click.argument("title")
@click.option("--issue", type=int, required=True)
@click.option("--severity", type=click.Choice(["critical", "high", "medium", "low"]))
def create_investigation(title, issue, severity):
    """Create an investigation document for bug analysis.

    Investigations track the process of debugging an issue.

    Examples:
        agenttree create-investigation "Race condition in session store" --issue 45 --severity critical
    """
    extra = {
        "issue_number": issue,
        "severity": severity,
        "status": "investigating"
    }
    _create_doc("investigation", title, INVESTIGATION_SCHEMA, extra)

# Namespaced management commands
@main.group()
def docs():
    """Manage agent documentation."""
    pass

@docs.command("list")
@click.option("--type", help="Filter by document type")
@click.option("--agent", type=int, help="Filter by agent number")
def list_docs(type, agent):
    """List all documentation files."""
    # Implementation...

@docs.command("validate")
@click.argument("file_path")
def validate(file_path):
    """Validate frontmatter in a markdown file."""
    # Implementation...
```

---

## Summary

### Pre-Creation Pattern

**Use for:**
- ✅ Context summaries (100% needed, critical for re-engagement)
- ✅ Task logs (already done)
- ✅ Spec files (already done)

**Benefits:**
- Zero friction (file exists when agent starts)
- Frontmatter pre-filled (git context at task start)
- Agent just fills content sections
- No "did I create it?" uncertainty

---

### CLI Design: Specialized Tools

**Use:**
```bash
agenttree create-note "Title"           # Top-level (frequent)
agenttree create-rfc "Title"            # Top-level (important)
agenttree create-investigation "Title"  # Top-level (sometimes)

agenttree docs list                     # Namespaced (management)
agenttree docs validate <file>          # Namespaced (management)
```

**Why better for AI agents:**
1. Clear intent (tool name = action)
2. Type-specific help text
3. Type-specific options
4. Better error messages
5. Discoverable via tab completion
6. Industry standard (like git)

---

## Next Steps

1. **Implement pre-creation of context summaries** in `dispatch()`
2. **Implement specialized creation tools** (create-note, create-rfc, create-investigation)
3. **Test with real agent** - Does pre-created context summary help?
4. **Iterate based on usage**

Which should I implement first?
- A) Pre-create context summaries (immediate value for re-engagement)
- B) create-rfc command (most complex, sets pattern for others)
- C) Both in parallel

My vote: **A + B together** - Pre-creation solves the "always needed" case, create-rfc solves the "sometimes needed" case. Together they validate both patterns.
