# Plan: Agents Repository Web UI & Frontmatter

**Date:** 2026-01-04
**Status:** Planning
**Goal:** Make _agenttree/ repository navigable via web UI with rich metadata and markdown rendering

## Problem Statement

Currently:
- ❌ Markdown files in _agenttree/ repo have no structured metadata
- ❌ No git commit tracking (which commits were made during this task?)
- ❌ Web dashboard only shows agent status, not work artifacts
- ❌ No way to browse task history, specs, or knowledge base via web
- ❌ No rendered markdown view (must clone repo to read docs)

## Proposed Solution

### Part 1: Add Frontmatter to All Markdown Files

**YAML frontmatter** at the top of every markdown file with:
- Git metadata (starting commit, branch, commits made, PR links)
- Task metadata (issue number, agent, dates)
- Cross-references (related files, dependencies)

### Part 2: Enhance Web Dashboard

**Three views:**
1. **Agent View** (current) - Agent status, live tmux
2. **Task View** (new) - Task-centric history with chat logs and artifacts
3. **File View** (new) - Browse _agenttree/ repo markdown files

**Features:**
- Render markdown as HTML
- Frontmatter displays as metadata cards
- Links to commits/PRs in main repo
- Search across all docs
- Timeline view of work

### Part 3: Future - Code Review UI

- Select text in markdown
- Add inline comments
- Submit feedback to agent (like GitHub PR reviews)
- Agent sees feedback in next task dispatch

---

## Part 1: Frontmatter Schemas

### General Principles

**Format:** YAML frontmatter (widely supported, parseable)
```yaml
---
key: value
list:
  - item1
  - item2
---
# Markdown content starts here
```

**Common fields across all types:**
```yaml
---
# Core identification
document_type: task_log | spec | rfc | investigation | note
created_at: 2026-01-04T10:30:00Z
updated_at: 2026-01-04T15:45:00Z
created_by: agent-1

# Git context (main project repo)
repo_url: https://github.com/user/project
starting_commit: abc123def456  # HEAD when task started
starting_branch: main          # Branch we branched from
work_branch: agent-1/fix-auth  # Branch for this work
commits: []                    # List of commit hashes made during work

# Related items
issue_number: 42
pr_number: 50
related_docs: []               # Paths to related docs in _agenttree/ repo
---
```

---

### Schema 1: Task Log

**Path:** `_agenttree/tasks/agent-{num}/{date}-{slug}.md`

**Purpose:** Track an agent's work on a specific task

**Frontmatter:**
```yaml
---
document_type: task_log
version: 1

# Task identification
task_id: agent-1-2026-01-04-fix-auth-bug
issue_number: 42
issue_title: "Fix authentication bug in login flow"
issue_url: https://github.com/user/project/issues/42
agent: agent-1

# Timeline
created_at: 2026-01-04T10:30:00Z
started_at: 2026-01-04T10:35:00Z
completed_at: 2026-01-04T15:45:00Z  # null if in progress
status: in_progress | completed | blocked | abandoned

# Git context (main project repo)
repo_url: https://github.com/user/project
starting_commit: abc123def456
starting_branch: main
work_branch: agent-1/fix-auth-bug
commits:
  - hash: def456ghi789
    message: "Add JWT token validation"
    timestamp: 2026-01-04T11:00:00Z
  - hash: ghi789jkl012
    message: "Fix token expiry check"
    timestamp: 2026-01-04T14:00:00Z

# Artifacts
pr_number: 50
pr_url: https://github.com/user/project/pull/50
pr_status: open | merged | closed

# Related documentation
spec_file: specs/features/issue-42.md
context_file: context/agent-1/issue-42.md  # Chat history/summary
related_tasks: []  # Other task logs related to this work

# Outcomes
files_changed:
  - src/auth/jwt.ts
  - src/api/client.ts
  - tests/auth.test.ts
tests_added: 5
tests_modified: 2

# Metadata
tags:
  - authentication
  - jwt
  - security
difficulty: medium
time_spent_minutes: 315  # 5.25 hours
---

# Task: Fix authentication bug in login flow

## Context

(Markdown content here...)
```

**Usage in CLI:**
```python
def create_task_file(agent_num, issue_num, issue_title, issue_body, issue_url):
    # Get current git context
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True
    ).stdout.strip()

    current_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True
    ).stdout.strip()

    frontmatter = {
        "document_type": "task_log",
        "version": 1,
        "task_id": f"agent-{agent_num}-{date}-{slug}",
        "issue_number": issue_num,
        "issue_title": issue_title,
        "issue_url": issue_url,
        "agent": f"agent-{agent_num}",
        "created_at": datetime.utcnow().isoformat() + "Z",
        "started_at": datetime.utcnow().isoformat() + "Z",
        "completed_at": None,
        "status": "in_progress",
        "repo_url": get_repo_url(),
        "starting_commit": current_commit,
        "starting_branch": current_branch,
        "work_branch": f"agent-{agent_num}/work",
        "commits": [],
        "tags": []
    }

    content = f"---\n{yaml.dump(frontmatter)}---\n\n# Task: {issue_title}\n\n{issue_body}"
```

---

### Schema 2: Spec File

**Path:** `_agenttree/specs/features/issue-{num}.md`

**Purpose:** Living documentation of a feature

**Frontmatter:**
```yaml
---
document_type: spec
version: 1
spec_type: feature | architecture | pattern | api

# Feature identification
feature_name: "JWT Authentication"
issue_number: 42
issue_url: https://github.com/user/project/issues/42
status: planning | in_progress | implemented | deprecated

# Timeline
created_at: 2026-01-04T10:30:00Z
updated_at: 2026-01-04T15:45:00Z
implemented_at: null

# Git context
repo_url: https://github.com/user/project
implemented_in_pr: 50
related_commits:
  - abc123  # Key commits that implemented this feature

# Cross-references
rfc: rfcs/001-jwt-auth.md          # Design RFC if exists
related_specs:
  - specs/architecture/auth.md
  - specs/patterns/token-refresh.md
tasks:
  - tasks/agent-1/2026-01-04-fix-auth.md
  - tasks/agent-2/2026-01-05-add-refresh.md

# Metadata
tags:
  - authentication
  - security
contributors:
  - agent-1
  - agent-2
last_updated_by: agent-1
---

# JWT Authentication

(Spec content...)
```

---

### Schema 3: RFC (Request for Comments)

**Path:** `_agenttree/rfcs/{number}-{slug}.md`

**Purpose:** Design proposals for major changes

**Frontmatter:**
```yaml
---
document_type: rfc
version: 1

# RFC identification
rfc_number: 1
title: "Implement JWT-based Authentication"
author: agent-1
status: proposed | accepted | rejected | implemented | superseded

# Timeline
proposed_at: 2026-01-04T10:00:00Z
decided_at: 2026-01-04T12:00:00Z
implemented_at: null

# Decision tracking
decision_maker: human | agent-1  # Who accepted/rejected
decision_rationale: "Provides better security than current session-based auth"

# Git context
repo_url: https://github.com/user/project
implemented_in_prs:
  - 50
  - 51
superseded_by: null  # RFC number that replaces this

# Cross-references
related_rfcs:
  - 2  # Related RFC on token refresh
related_specs:
  - specs/features/issue-42.md
tasks: []

# Metadata
tags:
  - architecture
  - authentication
  - breaking-change
complexity: high
estimated_effort_hours: 40
---

# RFC-001: Implement JWT-based Authentication

(RFC content...)
```

---

### Schema 4: Investigation

**Path:** `_agenttree/investigations/{date}-{slug}.md`

**Purpose:** Bug investigation or research notes

**Frontmatter:**
```yaml
---
document_type: investigation
version: 1

# Investigation identification
title: "Race condition in session store"
investigator: agent-2
status: investigating | root_cause_found | resolved

# Timeline
started_at: 2026-01-04T09:00:00Z
resolved_at: 2026-01-04T16:00:00Z

# Issue context
issue_number: 45
issue_url: https://github.com/user/project/issues/45
severity: critical | high | medium | low

# Git context
repo_url: https://github.com/user/project
starting_commit: abc123
affected_files:
  - src/session/store.go
  - src/session/manager.go

# Root cause
root_cause_commit: xyz789  # Commit that introduced the bug
root_cause_file: src/session/store.go
root_cause_line: 42

# Resolution
fixed_in_pr: 52
fixed_in_commits:
  - fix123

# Cross-references
related_investigations: []
related_tasks:
  - tasks/agent-2/2026-01-04-fix-race.md

# Metadata
tags:
  - bug
  - concurrency
  - race-condition
time_to_diagnose_hours: 4
---

# Investigation: Race condition in session store

(Investigation content...)
```

---

### Schema 5: Knowledge/Notes

**Path:** `_agenttree/notes/agent-{num}/{topic}.md`

**Purpose:** Agent's learnings and findings

**Frontmatter:**
```yaml
---
document_type: note
version: 1
note_type: gotcha | pattern | tip | question

# Note identification
title: "JWT Token Refresh Pattern"
author: agent-1

# Timeline
created_at: 2026-01-04T14:00:00Z
updated_at: 2026-01-04T14:30:00Z

# Context
discovered_in_task: tasks/agent-1/2026-01-04-fix-auth.md
issue_number: 42

# Applicability
applies_to_files:
  - src/auth/jwt.ts
  - src/api/client.ts
severity: important | nice_to_know  # For gotchas

# Cross-references
related_notes:
  - notes/agent-2/token-expiry.md
related_specs:
  - specs/patterns/token-refresh.md

# Metadata
tags:
  - authentication
  - best-practice
---

# JWT Token Refresh Pattern

(Note content...)
```

---

### Schema 6: Context Summary (for task re-engagement)

**Path:** `_agenttree/context/agent-{num}/issue-{num}.md`

**Purpose:** Summary of work for resuming later

**Frontmatter:**
```yaml
---
document_type: context_summary
version: 1

# Task context
task_id: agent-1-2026-01-04-fix-auth-bug
issue_number: 42
agent: agent-1

# Timeline
task_started: 2026-01-04T10:30:00Z
summary_created: 2026-01-04T15:45:00Z

# Git state
repo_url: https://github.com/user/project
work_branch: agent-1/fix-auth-bug
final_commit: def456ghi789
pr_number: 50
pr_status: open

# For resuming
resume_instructions: |
  Start by reviewing auth.test.ts
  Check if token expiry changed (was discussed)
  Be aware of cookie CORS issues

entry_point_file: src/auth/jwt.ts
key_files:
  - src/auth/jwt.ts: Main authentication logic
  - src/api/client.ts: API client integration
  - tests/auth.test.ts: Test coverage

# Work summary
commits_count: 5
files_changed_count: 8
tests_added: 5

# Cross-references
task_log: tasks/agent-1/2026-01-04-fix-auth.md
spec_file: specs/features/issue-42.md
notes_created:
  - notes/agent-1/jwt-refresh-pattern.md

# Metadata
tags:
  - authentication
  - resumable
---

# Context Summary: Fix authentication bug

## What Was Done

- Fixed JWT token validation
- Added token refresh logic
- Updated API client to handle auth

## Key Decisions

- Used localStorage for tokens (not cookies due to CORS)
- 1-hour expiry with automatic refresh
- Added error boundary for auth failures

## Gotchas Discovered

- Token refresh needs race condition handling
- Cookies don't work with our CORS setup

## For Resuming

If you need to continue this work:
1. Start by reading `tests/auth.test.ts`
2. Check if token expiry time changed (was debated)
3. Be aware of cookie/CORS incompatibility

(More context...)
```

---

## Part 2: Web UI Enhancements

### Architecture

**Current:**
```
FastAPI app
├── GET /                  # Dashboard (agent status)
├── GET /agents            # HTMX: agent list
├── GET /agent/{n}/tmux    # HTMX: tmux output
├── POST /agent/{n}/send   # Send command
└── WebSocket /ws/agent/{n}/tmux  # Live tmux stream
```

**Proposed:**
```
FastAPI app
├── Views
│   ├── GET /                           # Dashboard (agent status)
│   ├── GET /tasks                      # Task-centric view
│   ├── GET /files                      # File browser
│   └── GET /search                     # Search across all docs
│
├── Agent API
│   ├── GET /agents                     # HTMX: agent list
│   ├── GET /agent/{n}/tmux             # HTMX: tmux output
│   ├── POST /agent/{n}/send            # Send command
│   └── WebSocket /ws/agent/{n}/tmux    # Live tmux
│
├── Task API
│   ├── GET /tasks/list                 # HTMX: task list (all agents)
│   ├── GET /task/{id}                  # Task detail page
│   ├── GET /task/{id}/timeline         # Timeline of commits/events
│   ├── GET /task/{id}/context          # Context summary
│   └── GET /task/{id}/artifacts        # Related files/docs
│
└── File API
    ├── GET /files/browse               # Browse _agenttree/ repo
    ├── GET /files/view/{path}          # View markdown file (rendered)
    ├── GET /files/raw/{path}           # Raw markdown
    ├── GET /files/frontmatter/{path}   # Just frontmatter JSON
    └── GET /files/search?q={query}     # Search
```

---

### View 1: Dashboard (Enhanced)

**URL:** `/`

**Current:** Shows agent status table

**Enhancement:** Add quick stats and navigation

```html
┌────────────────────────────────────────────┐
│ AgentTree Dashboard                        │
├────────────────────────────────────────────┤
│ Quick Stats:                               │
│  • 3 Agents Active                         │
│  • 12 Tasks Completed This Week            │
│  • 8 Open PRs                              │
│  • 45 Docs in Knowledge Base               │
├────────────────────────────────────────────┤
│ Navigation:                                │
│  [Agents] [Tasks] [Files] [Search]         │
├────────────────────────────────────────────┤
│ Agent Status (current view)                │
│  Agent-1: Working on Issue #42             │
│  Agent-2: Idle                             │
│  Agent-3: Working on Issue #45             │
└────────────────────────────────────────────┘
```

---

### View 2: Task View (NEW)

**URL:** `/tasks`

**Purpose:** Task-centric view of all work

**Layout:**

```html
┌────────────────────────────────────────────────────────────┐
│ Tasks                                                      │
├────────────────────────────────────────────────────────────┤
│ Filters: [All] [In Progress] [Completed] [By Agent ▼]     │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ ┌──────────────────────────────────────────────────────┐  │
│ │ Issue #42: Fix authentication bug                    │  │
│ │ Agent: agent-1  |  Status: Completed  |  PR: #50     │  │
│ │ Started: 2026-01-04 10:30  |  Completed: 15:45       │  │
│ │                                                       │  │
│ │ Timeline:                                             │  │
│ │  10:30 ──────── 11:00 ──────── 14:00 ──────── 15:45  │  │
│ │  Start    Commit 1    Commit 2    PR Created         │  │
│ │                                                       │  │
│ │ Artifacts:                                            │  │
│ │  📝 Task Log                                          │  │
│ │  📄 Spec: JWT Authentication                          │  │
│ │  💡 Note: Token Refresh Pattern                       │  │
│ │  📋 Context Summary                                   │  │
│ │                                                       │  │
│ │ Git Changes:                                          │  │
│ │  • 5 commits on branch agent-1/fix-auth-bug          │  │
│ │  • 8 files changed                                    │  │
│ │  • PR #50: Merged ✓                                   │  │
│ │                                                       │  │
│ │ [View Full Details →]                                 │  │
│ └──────────────────────────────────────────────────────┘  │
│                                                            │
│ ┌──────────────────────────────────────────────────────┐  │
│ │ Issue #45: Race condition in session store           │  │
│ │ Agent: agent-2  |  Status: In Progress  |  PR: -     │  │
│ │ ...                                                   │  │
│ └──────────────────────────────────────────────────────┘  │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**Clicking "View Full Details"** takes you to `/task/{id}`:

```html
┌────────────────────────────────────────────────────────────┐
│ Task: Fix authentication bug (Issue #42)                   │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ Metadata Card:                                             │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ Agent: agent-1                                       │   │
│ │ Status: Completed ✓                                  │   │
│ │ Started: 2026-01-04 10:30                            │   │
│ │ Completed: 2026-01-04 15:45 (5.25 hours)             │   │
│ │ Issue: #42 [View on GitHub →]                        │   │
│ │ PR: #50 (Merged) [View on GitHub →]                  │   │
│ │ Branch: agent-1/fix-auth-bug                         │   │
│ │ Starting Commit: abc123 [View →]                     │   │
│ │ Tags: authentication, jwt, security                  │   │
│ └─────────────────────────────────────────────────────┘   │
│                                                            │
│ Timeline:                                                  │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ 10:30  Task started                                  │   │
│ │ 11:00  Commit: Add JWT token validation (def456)     │   │
│ │ 14:00  Commit: Fix token expiry check (ghi789)       │   │
│ │ 15:00  PR #50 created                                │   │
│ │ 15:45  Task completed                                │   │
│ │ 16:30  PR #50 merged                                 │   │
│ └─────────────────────────────────────────────────────┘   │
│                                                            │
│ Context Summary:                                           │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ What Was Done:                                       │   │
│ │ • Fixed JWT token validation                         │   │
│ │ • Added token refresh logic                          │   │
│ │ • Updated API client to handle auth                  │   │
│ │                                                       │   │
│ │ Key Decisions:                                       │   │
│ │ • Used localStorage (not cookies due to CORS)        │   │
│ │ • 1-hour expiry with auto-refresh                    │   │
│ │                                                       │   │
│ │ Gotchas:                                             │   │
│ │ • Token refresh needs race condition handling        │   │
│ │ • Cookies incompatible with CORS setup               │   │
│ └─────────────────────────────────────────────────────┘   │
│                                                            │
│ Related Files:                                             │
│ • 📝 Task Log [View →]                                     │
│ • 📄 Spec: JWT Authentication [View →]                     │
│ • 💡 Note: Token Refresh Pattern [View →]                  │
│ • 🔍 Investigation: (none)                                 │
│                                                            │
│ Git Changes (8 files):                                     │
│ • src/auth/jwt.ts (+120, -30)                              │
│ • src/api/client.ts (+45, -10)                             │
│ • tests/auth.test.ts (+95, -0) [5 new tests]               │
│ • ...                                                      │
│                                                            │
│ [View Task Log →] [View Chat History →]                    │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

### View 3: File Browser (NEW)

**URL:** `/files`

**Purpose:** Browse _agenttree/ repository markdown files

**Layout:**

```html
┌────────────────────────────────────────────────────────────┐
│ Files - Browse Agents Repository                          │
├────────────────────────────────────────────────────────────┤
│ Path: / _agenttree/                                            │
│                                                            │
│ Search: [_____________________] [🔍 Search]                │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ 📁 specs/                                                  │
│   📁 architecture/                                         │
│   📁 features/                                             │
│     📄 issue-42.md  (JWT Authentication)                   │
│     📄 issue-45.md  (Session Store Fix)                    │
│   📁 patterns/                                             │
│     📄 token-refresh.md                                    │
│                                                            │
│ 📁 tasks/                                                  │
│   📁 agent-1/                                              │
│     📄 2026-01-04-fix-auth-bug.md  ✓ Completed             │
│     📄 2026-01-03-add-logging.md   ✓ Completed             │
│   📁 agent-2/                                              │
│     📄 2026-01-05-session-race.md  🔄 In Progress          │
│   📁 archive/                                              │
│                                                            │
│ 📁 rfcs/                                                   │
│   📄 001-jwt-auth.md  (Accepted)                           │
│   📄 002-token-refresh.md  (Proposed)                      │
│                                                            │
│ 📁 knowledge/                                              │
│   📄 gotchas.md                                            │
│   📄 decisions.md                                          │
│   📄 onboarding.md                                         │
│                                                            │
│ 📁 notes/                                                  │
│   📁 agent-1/                                              │
│     📄 jwt-refresh-pattern.md                              │
│   📁 agent-2/                                              │
│     📄 session-storage.md                                  │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**Clicking a file** takes you to `/files/view/{path}`:

```html
┌────────────────────────────────────────────────────────────┐
│ File: specs/features/issue-42.md                           │
├────────────────────────────────────────────────────────────┤
│ [< Back to Files]  [Raw] [Edit on GitHub]                  │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ Metadata:                                                  │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ Type: Feature Spec                                   │   │
│ │ Feature: JWT Authentication                          │   │
│ │ Status: Implemented ✓                                │   │
│ │ Issue: #42 [View →]                                  │   │
│ │ Implemented in PR: #50 [View →]                      │   │
│ │ Created: 2026-01-04 10:30                            │   │
│ │ Last updated: 2026-01-04 15:45 by agent-1            │   │
│ │ Tags: authentication, security                       │   │
│ │                                                       │   │
│ │ Related Docs:                                        │   │
│ │ • RFC-001: JWT Auth [View →]                         │   │
│ │ • Pattern: Token Refresh [View →]                    │   │
│ │ • Task: Fix auth bug [View →]                        │   │
│ └─────────────────────────────────────────────────────┘   │
│                                                            │
│ ┌─────────────────────────────────────────────────────┐   │
│ │ # JWT Authentication                                 │   │
│ │                                                       │   │
│ │ (Rendered markdown content here...)                  │   │
│ │                                                       │   │
│ │ ## Overview                                          │   │
│ │                                                       │   │
│ │ This feature implements JWT-based authentication...  │   │
│ │                                                       │   │
│ └─────────────────────────────────────────────────────┘   │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

### View 4: Search (NEW)

**URL:** `/search?q=authentication`

**Purpose:** Search across all markdown files

```html
┌────────────────────────────────────────────────────────────┐
│ Search Results for "authentication"                        │
├────────────────────────────────────────────────────────────┤
│ Found 8 results in 6 files                                 │
│                                                            │
│ Filters: [All] [Specs] [Tasks] [RFCs] [Notes]             │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ 📄 specs/features/issue-42.md                              │
│    JWT Authentication - Feature Spec                       │
│    ...implements JWT-based **authentication** to replace  │
│    session-based auth. The **authentication** flow...      │
│    [View File →]                                           │
│                                                            │
│ 📝 tasks/agent-1/2026-01-04-fix-auth-bug.md                │
│    Task Log - Fix authentication bug                       │
│    ...the **authentication** header was not being sent     │
│    correctly in API requests...                            │
│    [View File →]                                           │
│                                                            │
│ 📋 rfcs/001-jwt-auth.md                                    │
│    RFC-001: Implement JWT-based Authentication             │
│    ...proposes replacing cookie-based **authentication**   │
│    with stateless JWT tokens...                            │
│    [View File →]                                           │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## Part 3: Implementation Plan

### Phase 1: Add Frontmatter Support

**Files to modify:**
- `agents_repo.py` - Update all `create_*_file()` methods

**Steps:**

1. **Add utility functions** (new file: `agenttree/frontmatter.py`):
   ```python
   import yaml
   from typing import Dict, Any
   from datetime import datetime

   def create_frontmatter(data: Dict[str, Any]) -> str:
       """Create YAML frontmatter block."""
       return f"---\n{yaml.dump(data, default_flow_style=False)}---\n\n"

   def parse_frontmatter(content: str) -> tuple[Dict, str]:
       """Parse frontmatter and content from markdown."""
       if not content.startswith("---"):
           return {}, content

       parts = content.split("---", 2)
       frontmatter = yaml.safe_load(parts[1])
       markdown = parts[2].strip()
       return frontmatter, markdown

   def get_git_context(repo_path: Path) -> Dict[str, Any]:
       """Get current git context (commit, branch)."""
       current_commit = subprocess.run(
           ["git", "rev-parse", "HEAD"],
           cwd=repo_path, capture_output=True, text=True
       ).stdout.strip()

       current_branch = subprocess.run(
           ["git", "rev-parse", "--abbrev-ref", "HEAD"],
           cwd=repo_path, capture_output=True, text=True
       ).stdout.strip()

       repo_url = subprocess.run(
           ["git", "config", "--get", "remote.origin.url"],
           cwd=repo_path, capture_output=True, text=True
       ).stdout.strip()

       return {
           "repo_url": repo_url,
           "starting_commit": current_commit,
           "starting_branch": current_branch,
       }
   ```

2. **Update `create_task_file()`**:
   ```python
   def create_task_file(self, agent_num, issue_num, issue_title, issue_body, issue_url):
       # Get git context from main project
       git_ctx = get_git_context(self.project_path)

       frontmatter = {
           "document_type": "task_log",
           "version": 1,
           "task_id": f"agent-{agent_num}-{date}-{slug}",
           "issue_number": issue_num,
           "issue_title": issue_title,
           "issue_url": issue_url,
           "agent": f"agent-{agent_num}",
           "created_at": datetime.utcnow().isoformat() + "Z",
           "started_at": datetime.utcnow().isoformat() + "Z",
           "completed_at": None,
           "status": "in_progress",
           **git_ctx,
           "work_branch": f"agent-{agent_num}/work",
           "commits": [],
           "pr_number": None,
           "spec_file": f"specs/features/issue-{issue_num}.md",
           "tags": []
       }

       content = create_frontmatter(frontmatter)
       content += f"# Task: {issue_title}\n\n"
       content += f"{issue_body}\n"

       task_file.write_text(content)
   ```

3. **Update `create_spec_file()`**, `create_rfc()`, etc. similarly

4. **Add commit tracking**:
   - When task completes, parse task log frontmatter
   - Get list of commits on work branch: `git log starting_commit..HEAD`
   - Update `commits` array in frontmatter

---

### Phase 2: Web UI - Backend API

**Files to create/modify:**
- `agenttree/web/app.py` - Add new routes
- `agenttree/web/models.py` (new) - Pydantic models for frontmatter
- `agenttree/web/agents_reader.py` (new) - Read _agenttree/ repo

**Steps:**

1. **Create _agenttree/ repo reader** (`agents_reader.py`):
   ```python
   from pathlib import Path
   from typing import List, Dict, Optional
   from agenttree.frontmatter import parse_frontmatter

   class AgentsRepoReader:
       def __init__(self, agents_path: Path):
           self.agents_path = agents_path

       def list_tasks(self, agent_num: Optional[int] = None) -> List[Dict]:
           """List all task logs."""
           tasks = []
           tasks_dir = self.agents_path / "tasks"

           for task_file in tasks_dir.glob("**/**.md"):
               if task_file.parent.name == "archive":
                   continue

               content = task_file.read_text()
               frontmatter, _ = parse_frontmatter(content)

               if frontmatter and (not agent_num or frontmatter.get("agent") == f"agent-{agent_num}"):
                   tasks.append({
                       "path": str(task_file.relative_to(self.agents_path)),
                       "frontmatter": frontmatter,
                       "file": task_file
                   })

           return sorted(tasks, key=lambda x: x["frontmatter"].get("created_at", ""), reverse=True)

       def get_file(self, path: str) -> Dict:
           """Get a file with frontmatter and content."""
           file_path = self.agents_path / path
           content = file_path.read_text()
           frontmatter, markdown = parse_frontmatter(content)

           return {
               "path": path,
               "frontmatter": frontmatter,
               "markdown": markdown,
               "raw": content
           }

       def search(self, query: str) -> List[Dict]:
           """Search all markdown files."""
           results = []

           for md_file in self.agents_path.glob("**/*.md"):
               content = md_file.read_text()

               if query.lower() in content.lower():
                   frontmatter, markdown = parse_frontmatter(content)

                   # Find matching lines
                   lines = content.split("\n")
                   matches = [line for line in lines if query.lower() in line.lower()]

                   results.append({
                       "path": str(md_file.relative_to(self.agents_path)),
                       "frontmatter": frontmatter,
                       "matches": matches[:3]  # First 3 matches
                   })

           return results
   ```

2. **Add routes to `app.py`**:
   ```python
   from agenttree.web.agents_reader import AgentsRepoReader
   import markdown  # For rendering markdown

   # Initialize reader
   agents_reader = None  # Set in run_server()

   @app.get("/tasks", response_class=HTMLResponse)
   async def tasks_view(request: Request):
       """Task-centric view."""
       get_current_user()
       tasks = agents_reader.list_tasks() if agents_reader else []
       return templates.TemplateResponse(
           "tasks.html",
           {"request": request, "tasks": tasks}
       )

   @app.get("/task/{task_id}", response_class=HTMLResponse)
   async def task_detail(request: Request, task_id: str):
       """Task detail page."""
       get_current_user()
       # Parse task_id (e.g., "agent-1-2026-01-04-fix-auth")
       # Find task file
       # Load frontmatter + content
       # Render template
       pass

   @app.get("/files", response_class=HTMLResponse)
   async def files_browser(request: Request, path: str = ""):
       """Browse _agenttree/ repo files."""
       get_current_user()
       # List directory contents
       # Return file browser template
       pass

   @app.get("/files/view/{path:path}", response_class=HTMLResponse)
   async def file_view(request: Request, path: str):
       """View markdown file (rendered)."""
       get_current_user()
       file_data = agents_reader.get_file(path)

       # Render markdown to HTML
       html = markdown.markdown(
           file_data["markdown"],
           extensions=['tables', 'fenced_code', 'codehilite']
       )

       return templates.TemplateResponse(
           "file_view.html",
           {
               "request": request,
               "path": path,
               "frontmatter": file_data["frontmatter"],
               "html": html
           }
       )

   @app.get("/search", response_class=HTMLResponse)
   async def search(request: Request, q: str):
       """Search markdown files."""
       get_current_user()
       results = agents_reader.search(q) if agents_reader else []
       return templates.TemplateResponse(
           "search.html",
           {"request": request, "query": q, "results": results}
       )
   ```

---

### Phase 3: Web UI - Frontend Templates

**Files to create:**
- `templates/tasks.html`
- `templates/task_detail.html`
- `templates/files.html`
- `templates/file_view.html`
- `templates/search.html`
- `templates/partials/frontmatter_card.html`
- `templates/partials/timeline.html`

**Example: `templates/file_view.html`**:
```html
<!DOCTYPE html>
<html>
<head>
    <title>{{ path }} - AgentTree</title>
    <link rel="stylesheet" href="/static/style.css">
    <link rel="stylesheet" href="/static/markdown.css">
</head>
<body>
    <nav>
        <a href="/">Dashboard</a> |
        <a href="/tasks">Tasks</a> |
        <a href="/files">Files</a> |
        <a href="/search">Search</a>
    </nav>

    <main>
        <h1>{{ path }}</h1>
        <a href="/files">← Back to Files</a>

        <!-- Frontmatter Metadata Card -->
        {% if frontmatter %}
        <div class="metadata-card">
            <h2>Metadata</h2>
            <dl>
                <dt>Type:</dt>
                <dd>{{ frontmatter.document_type }}</dd>

                <dt>Created:</dt>
                <dd>{{ frontmatter.created_at }}</dd>

                {% if frontmatter.issue_number %}
                <dt>Issue:</dt>
                <dd>
                    <a href="{{ frontmatter.issue_url }}" target="_blank">
                        #{{ frontmatter.issue_number }}
                    </a>
                </dd>
                {% endif %}

                {% if frontmatter.pr_number %}
                <dt>PR:</dt>
                <dd>
                    <a href="{{ frontmatter.pr_url }}" target="_blank">
                        #{{ frontmatter.pr_number }}
                    </a>
                </dd>
                {% endif %}

                {% if frontmatter.starting_commit %}
                <dt>Starting Commit:</dt>
                <dd>
                    <a href="{{ frontmatter.repo_url }}/commit/{{ frontmatter.starting_commit }}" target="_blank">
                        {{ frontmatter.starting_commit[:7] }}
                    </a>
                </dd>
                {% endif %}

                {% if frontmatter.commits %}
                <dt>Commits:</dt>
                <dd>
                    <ul>
                    {% for commit in frontmatter.commits %}
                        <li>
                            <a href="{{ frontmatter.repo_url }}/commit/{{ commit.hash }}" target="_blank">
                                {{ commit.hash[:7] }}
                            </a>
                            - {{ commit.message }}
                        </li>
                    {% endfor %}
                    </ul>
                </dd>
                {% endif %}

                {% if frontmatter.tags %}
                <dt>Tags:</dt>
                <dd>
                    {% for tag in frontmatter.tags %}
                        <span class="tag">{{ tag }}</span>
                    {% endfor %}
                </dd>
                {% endif %}
            </dl>
        </div>
        {% endif %}

        <!-- Rendered Markdown -->
        <div class="markdown-content">
            {{ html | safe }}
        </div>
    </main>
</body>
</html>
```

---

### Phase 4: CSS Styling

**Files to create:**
- `static/style.css` - Main styles
- `static/markdown.css` - Markdown rendering styles

**Example styles:**
```css
/* static/style.css */
.metadata-card {
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 1rem;
    margin: 1rem 0;
}

.metadata-card dl {
    display: grid;
    grid-template-columns: 150px 1fr;
    gap: 0.5rem;
}

.metadata-card dt {
    font-weight: bold;
}

.tag {
    background: #007bff;
    color: white;
    padding: 2px 8px;
    border-radius: 3px;
    font-size: 0.9em;
    margin-right: 5px;
}

.timeline {
    position: relative;
    padding: 1rem 0;
}

.timeline-item {
    margin: 1rem 0;
    padding-left: 2rem;
    border-left: 2px solid #007bff;
}

.markdown-content {
    max-width: 800px;
    margin: 2rem auto;
    padding: 2rem;
    background: white;
    border: 1px solid #ddd;
    border-radius: 4px;
}
```

---

## Part 4: Future - Code Review UI

**Goal:** Allow users to comment on markdown files like GitHub code reviews

**Implementation approach:**

1. **Store comments** in separate file:
   ```
   _agenttree/comments/agent-1/2026-01-04-fix-auth.comments.json
   ```

   Schema:
   ```json
   {
     "file": "tasks/agent-1/2026-01-04-fix-auth.md",
     "comments": [
       {
         "id": "c1",
         "line_start": 45,
         "line_end": 48,
         "selected_text": "Used localStorage for tokens",
         "comment": "Why not cookies? Have you considered httpOnly cookies for security?",
         "author": "user@example.com",
         "created_at": "2026-01-05T10:00:00Z",
         "status": "open"
       }
     ]
   }
   ```

2. **JavaScript for text selection**:
   ```javascript
   // In file view, allow text selection and commenting
   document.addEventListener('mouseup', function() {
       const selection = window.getSelection();
       if (selection.toString().length > 0) {
           showCommentButton(selection);
       }
   });

   function showCommentButton(selection) {
       // Show floating "Add Comment" button
       // On click, open comment form
   }
   ```

3. **Submit comments**:
   ```python
   @app.post("/files/{path:path}/comment")
   async def add_comment(
       path: str,
       line_start: int,
       line_end: int,
       selected_text: str,
       comment: str
   ):
       # Save comment to JSON file
       # Return updated comments list
   ```

4. **Show comments in sidebar**:
   - Highlight commented text
   - Show comment threads in sidebar
   - Allow resolving comments

5. **Dispatch feedback to agent**:
   ```python
   @app.post("/task/{task_id}/submit-review")
   async def submit_review(task_id: str):
       # Gather all unresolved comments
       # Create new TASK.md with feedback
       # Dispatch to agent
   ```

---

## Dependencies

**Python packages to add:**

```toml
# pyproject.toml
[project.dependencies]
...existing...
"markdown>=3.5",        # Markdown to HTML
"pygments>=2.17",       # Syntax highlighting
"pyyaml>=6.0",          # YAML frontmatter
```

**Install:**
```bash
uv add markdown pygments pyyaml
```

---

## Testing Plan

1. **Unit tests for frontmatter**:
   - Test `create_frontmatter()`
   - Test `parse_frontmatter()`
   - Test `get_git_context()`

2. **Integration tests for web UI**:
   - Test task list endpoint
   - Test file view endpoint
   - Test search endpoint
   - Test markdown rendering

3. **Manual testing**:
   - Create task with frontmatter
   - View in web UI
   - Verify all links work
   - Test search

---

## Rollout Plan

### Week 1: Frontmatter Foundation
- [ ] Create `frontmatter.py` utility module
- [ ] Add frontmatter to task logs
- [ ] Add frontmatter to spec files
- [ ] Add commit tracking on task completion
- [ ] Test with real tasks

### Week 2: Web Backend
- [ ] Create `AgentsRepoReader` class
- [ ] Add `/tasks` endpoint
- [ ] Add `/files` endpoint
- [ ] Add `/search` endpoint
- [ ] Add markdown rendering

### Week 3: Web Frontend
- [ ] Create task list template
- [ ] Create task detail template
- [ ] Create file browser template
- [ ] Create file view template
- [ ] Add CSS styling

### Week 4: Polish & Documentation
- [ ] Add navigation between views
- [ ] Improve search with filters
- [ ] Add timeline visualization
- [ ] Write user guide
- [ ] Update AGENT_GUIDE.md

### Future (Phase 2):
- [ ] Code review UI (text selection + comments)
- [ ] Comment storage and threading
- [ ] Dispatch feedback to agents

---

## Success Criteria

After implementation:

✅ **All markdown files have frontmatter** with git context
✅ **Web UI has 3 views**: Agents, Tasks, Files
✅ **Markdown files render as HTML** with syntax highlighting
✅ **Frontmatter displays as metadata cards** with links to commits/PRs
✅ **Search works across all documents**
✅ **Users can browse task history** without cloning repo
✅ **Timeline view shows task progress** over time

**Future:**
✅ Users can comment on markdown files
✅ Comments dispatch as feedback to agents

---

## Open Questions

1. **Should we version frontmatter schemas?**
   - Yes, include `version: 1` field for future changes

2. **Should we auto-update frontmatter when commits are made?**
   - Yes, on task completion, scan git log and update commits array

3. **How to handle large commit lists?**
   - Link to "View all N commits on GitHub" instead of listing all

4. **Should we store rendered HTML or render on-demand?**
   - Render on-demand (simpler, always up-to-date)

5. **Access control for web UI?**
   - Use existing AUTH_ENABLED with HTTP Basic Auth
   - Future: Add role-based access (view-only vs admin)

---

## Next Steps

**Immediate:**
1. Review this plan with team
2. Confirm frontmatter schemas
3. Prioritize Phase 1 vs Phase 2 vs Phase 3

**Then:**
1. Start with Phase 1 (frontmatter)
2. Test with real usage
3. Gather feedback
4. Proceed to web UI phases

Would you like me to start implementing Phase 1 (frontmatter support)?
