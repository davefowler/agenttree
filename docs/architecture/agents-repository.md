# Agents Repository Architecture

**Status:** Implemented in v0.1.0
**Last Updated:** 2026-01-01

## Overview

The Agents Repository is a separate GitHub repository (`{project}-agents`) that stores AI-generated documentation, task logs, and accumulated knowledge. It's automatically created and managed by AgentTree to keep the main project repository clean.

## Design Goals

1. **Separation of Concerns** - AI content doesn't clutter main repo
2. **Persistent Memory** - Knowledge survives agent sessions
3. **Collaboration** - Agents share context through specs
4. **Discoverability** - Structured, searchable documentation
5. **Automatic Management** - AgentTree handles git operations

## Repository Structure

```
{project}-agents/
├── README.md              # Auto-generated overview
├── AGENTS.md             # Instructions for AI agents
│
├── templates/            # Reusable templates
│   ├── feature-spec.md   # Feature specification template
│   ├── rfc.md            # RFC (Request for Comments) template
│   ├── task-log.md       # Task execution log template
│   └── investigation.md  # Investigation/research template
│
├── specs/                # Living documentation
│   ├── architecture/     # System architecture docs
│   ├── features/         # Feature specifications (from issues)
│   └── patterns/         # Design patterns and conventions
│
├── tasks/                # Agent task execution logs
│   ├── agent-1/          # Agent-1's task logs (chronological)
│   ├── agent-2/          # Agent-2's task logs
│   └── archive/          # Completed tasks (organized by YYYY-MM)
│       └── 2026-01/      # Month-based folders
│
├── rfcs/                 # Design proposals
│   └── archive/          # Accepted/rejected RFCs
│
├── plans/                # Active planning documents
│   └── archive/          # Completed plans
│
└── knowledge/            # Accumulated learnings
    ├── gotchas.md        # Known issues, edge cases, workarounds
    ├── decisions.md      # Architecture Decision Records (ADRs)
    └── onboarding.md     # What new agents/humans should know
```

## File Naming Conventions

### Task Logs
Format: `YYYY-MM-DD-{slug}.md`

Example: `2026-01-15-add-dark-mode.md`

- Date prefix enables chronological sorting
- Slug derived from issue title
- Automatically moved to archive when completed

### Specs
Format: `issue-{number}.md` or `{slug}.md`

Examples:
- `issue-42.md` (from GitHub issue #42)
- `authentication-system.md` (manual spec)

### RFCs
Format: `YYYY-MM-DD-{slug}.md`

Example: `2026-01-15-container-abstraction.md`

## Lifecycle

### 1. Repository Creation

When `agenttree init` runs:

```python
# Check if _agenttree/.git exists
if not (project_path / "_agenttree" / ".git").exists():
    # Create GitHub repo: {project-name}-agents
    gh repo create {project}-agents --private

    # Clone locally
    git clone git@github.com:user/{project}-agents.git _agenttree/

    # Initialize structure
    create_folder_structure()
    create_templates()
    create_knowledge_files()

    # Add to .gitignore
    echo "_agenttree/" >> .gitignore
```

### 2. Task Dispatch

When `agenttree start 1 42` runs:

```python
# Create/update spec from issue
agents_repo.create_spec_file(
    issue_num=42,
    issue_title="Add dark mode",
    issue_body="...",
    issue_url="https://github.com/..."
)
# Creates: specs/features/issue-42.md

# Create task log for agent
task_path = agents_repo.create_task_file(
    agent_num=1,
    issue_num=42,
    issue_title="Add dark mode",
    ...
)
# Creates: tasks/agent-1/2026-01-15-add-dark-mode.md

# Auto-commit and push
git add . && git commit -m "Start task: Add dark mode" && git push
```

### 3. Task Completion

When agent finishes:

```python
# Archive completed task
agents_repo.archive_task(agent_num=1)
# Moves: tasks/agent-1/2026-01-15-add-dark-mode.md
#     → tasks/archive/2026-01/agent-1-add-dark-mode.md
```

## Templates

### Feature Spec Template

Follows a simplified RFC-like format:

```markdown
# {Feature Title}

**Issue:** [#{number}](url)
**Created:** YYYY-MM-DD
**Status:** In Progress | Completed | On Hold

## Summary
[One paragraph overview]

## Motivation
[Why we need this]

## Detailed Design
[How it works]

## Alternatives Considered
[What else we looked at]

## Open Questions
- [ ] Question 1
- [ ] Question 2
```

### Task Log Template

Captures execution progress:

```markdown
# Task: {Title}

**Date:** YYYY-MM-DD
**Agent:** agent-{N}
**Issue:** [#{number}](url)
**Status:** In Progress

## Description
{Issue body}

## Progress Log
<!-- Agent updates this section -->

### YYYY-MM-DD HH:MM
- Started work
- Initial exploration findings

## Challenges
- Challenge 1 and how solved

## Outcome
- [ ] Task incomplete
- [ ] Task complete - PR #{number}
```

## Git Operations

All git operations auto-commit and push:

```python
def _commit(self, message: str) -> None:
    """Commit and push changes."""
    subprocess.run(["git", "add", "."], cwd=agents_path)
    subprocess.run(["git", "commit", "-m", message], cwd=agents_path)
    subprocess.run(["git", "push"], cwd=agents_path)
```

**Why auto-push?**
- Ensures agents' work is backed up
- Enables team visibility
- Prevents loss if agent session crashes
- Simpler than manual push requirements

## Integration Points

### CLI Integration

```bash
# Create agents repo
agenttree init
  → AgentsRepository.ensure_repo()

# Dispatch creates spec + task log
agenttree start 1 42
  → AgentsRepository.create_spec_file(42, ...)
  → AgentsRepository.create_task_file(1, 42, ...)

# View task logs
agenttree notes show 1
  → Lists tasks/agent-1/*.md

# Search documentation
agenttree notes search "auth"
  → Greps across all markdown files

# Archive completed work
agenttree notes archive 1
  → Moves latest task to archive/
```

### Agent Instructions (AGENTS.md)

The `AGENTS.md` file tells AI agents how to use the repository:

```markdown
# Agent Documentation Guide

You are an AI agent working on {project}. This repository tracks your work.

## Your Current Task

Check `tasks/agent-{N}/YYYY-MM-DD-*.md` for your current assignment.

## Updating Docs

### When Starting
1. Read the task log
2. Read relevant specs in `specs/`
3. Note any gotchas in `knowledge/gotchas.md`

### During Work
Update your task log with progress, challenges, learnings.

### When Stuck
1. Search `knowledge/` for similar issues
2. Check `specs/` for requirements
3. Review `tasks/archive/` for past solutions

### When Complete
Document learnings in `knowledge/gotchas.md` or `decisions.md`
```

## Design Decisions

### Why Separate Repository?

**Options Considered:**
1. `.agenttree/` folder in main repo
2. Git submodule
3. Separate repo (chosen)

**Rationale:**
- ✅ Keeps main repo clean (major user pain point)
- ✅ Separate commit history for AI content
- ✅ Can grant different access permissions
- ✅ Easier to ignore/delete if unwanted
- ✅ No submodule complexity
- ❌ Slight overhead (two repos to clone)

### Why Auto-Commit/Push?

**Alternatives:**
- Manual commit by user
- Commit but don't push
- No git operations

**Rationale:**
- ✅ Never lose agent work
- ✅ Team can see progress
- ✅ Simpler for agents
- ❌ More git noise (acceptable trade-off)

### Why RFC Format?

Researched multiple formats:
- RFCs (Rust, Python)
- ADRs (Architecture Decision Records)
- Google Docs templates
- Spec-kit format

Chose RFC-inspired because:
- ✅ Well-understood format
- ✅ Encourages thorough thinking
- ✅ Captures alternatives
- ✅ Lightweight (not formal)

See: `docs/planning/agent-notes-research.md`

## Future Enhancements

### v0.2.0
- Search command with fuzzy matching
- Link detection (find related specs/tasks)
- Metrics (task completion time, common issues)

### v0.3.0
- Web UI for browsing agents repo
- Visual timeline of agent work
- Automatic knowledge extraction (ML-based)

### v1.0.0
- Cross-project knowledge sharing
- Agent learning from past mistakes
- Automatic spec validation

## References

- Planning Research: `docs/planning/agent-notes-research.md`
- Implementation Plan: `docs/planning/implementation-plan.md`
- Code: `agenttree/agents_repo.py`
- Tests: `tests/unit/test_agents_repo.py`
