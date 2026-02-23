# Agent Notes & Documentation Framework Research

## Existing Frameworks

### 1. GitHub's Spec-Kit

**What it is:** Template repository for product specifications

**Structure:**
```
specs/
├── _templates/
│   ├── feature-spec.md
│   └── rfc.md
├── features/
│   ├── dark-mode.md
│   └── real-time-sync.md
└── rfcs/
    └── 001-api-redesign.md
```

**Key insights:**
- ✅ Templates for consistency
- ✅ Separate folders by type (features vs RFCs)
- ✅ All specs live together (easy to search)
- ✅ Markdown for everything

**What they DON'T solve:**
- No task execution logs
- No agent collaboration tracking
- No archival strategy

### 2. OpenAI's Codex Patterns

**Observed patterns from Codex/ChatGPT code mode:**
- Keep session context in memory
- Export conversations as markdown
- No persistent documentation system

**Insight:** Most AI tools have NO persistence layer - this is a gap!

### 3. Cursor's `.cursorrules`

**Structure:**
```
.cursorrules          # Single file with project context
```

**Key insights:**
- ✅ Project-level context for AI
- ✅ Lives in repo root
- ❌ Single file gets unwieldy

### 4. Aider's `.aider*` files

**Structure:**
```
.aider.conf.yml       # Configuration
.aiderignore          # Files to ignore
```

**Key insights:**
- Minimal - just config
- No documentation/notes system

### 5. Notion Engineering Wikis

**Structure (typical eng team):**
```
📁 Engineering
  📁 Architecture
    - System Overview
    - API Design Principles
  📁 RFCs
    - RFC-001: Database Migration
  📁 Runbooks
    - Deploy Process
    - Incident Response
  📁 Meeting Notes
    - 2024-01-15 Planning
```

**Key insights:**
- ✅ Clear hierarchy
- ✅ Separation of living docs vs historical logs
- ✅ Templates for RFCs, runbooks

## Proposed AgentTree Structure

### High-Level Structure

```
<project>-agents/                 # Separate git repo
├── README.md                     # Auto-generated overview
├── .agentignore                  # What not to track
│
├── templates/                    # Templates for agents to use
│   ├── feature-spec.md
│   ├── task-log.md
│   └── investigation.md
│
├── specs/                        # Living documentation
│   ├── README.md                 # Index of all specs
│   ├── architecture/
│   │   ├── overview.md
│   │   ├── database.md
│   │   └── api-design.md
│   ├── features/
│   │   ├── authentication.md
│   │   └── real-time-sync.md
│   └── patterns/                 # Discovered patterns
│       ├── error-handling.md
│       └── testing-strategy.md
│
├── tasks/                        # Task execution logs
│   ├── agent-1/
│   │   ├── 2025-01-15-fix-login-bug.md
│   │   └── 2025-01-16-add-dark-mode.md
│   ├── agent-2/
│   │   └── 2025-01-15-refactor-api.md
│   └── README.md                 # Recent tasks
│
├── conversations/                # Agent-to-agent discussions
│   ├── 2025-01-15-architecture-debate.md
│   └── 2025-01-16-testing-strategy.md
│
├── plans/                        # Active planning documents
│   ├── README.md                 # Current active plans
│   ├── q1-2025-roadmap.md
│   ├── database-migration.md
│   └── archive/                  # Completed/obsolete plans
│       └── 2024-q4-migration.md
│
└── knowledge/                    # Accumulated learnings
    ├── gotchas.md                # Known issues and workarounds
    ├── decisions.md              # ADRs (Architecture Decision Records)
    └── onboarding.md             # What new agents/humans should know
```

### Detailed Structure Rationale

#### `/templates/`

**Purpose:** Consistency across agent outputs

**Contents:**
```markdown
# templates/feature-spec.md
# Feature: [Name]

## Overview
Brief description of what this feature does.

## User Stories
- As a [user type], I want to [action] so that [benefit]

## Technical Approach
How this will be implemented.

## Open Questions
What's unclear or needs discussion?

## Related
- Issues: #123
- Specs: [link]
```

**Templates needed:**
- `feature-spec.md` - For new features
- `task-log.md` - Daily work log format
- `investigation.md` - For bug investigations
- `rfc.md` - For architectural proposals

#### `/specs/` - Living Documentation

**Purpose:** Single source of truth maintained by agents

**Key principle:** These are LIVING documents that get updated as the codebase evolves.

**Structure:**
```
specs/
├── README.md              # Auto-generated index
├── architecture/
│   ├── overview.md        # System architecture (updated regularly)
│   ├── database.md        # DB schema, updated on migrations
│   └── api-design.md      # API patterns
├── features/
│   └── [feature].md       # One file per major feature
└── patterns/
    └── [pattern].md       # Discovered best practices
```

**Update flow:**
1. Agent completes feature
2. Agent updates relevant spec
3. Spec commit message: "Update auth.md after implementing 2FA"

#### `/tasks/` - Execution Logs

**Purpose:** Historical record of what agents did

**Naming:** `tasks/<agent-name>/YYYY-MM-DD-<slug>.md`

**Example:**
```markdown
# Task: Fix Login Bug

**Date:** 2025-01-15
**Agent:** agent-1
**Issue:** #42
**Status:** ✅ Completed

## What I Did

1. Investigated timeout issue in authentication flow
2. Found race condition in session store
3. Fixed by adding mutex lock
4. Added regression test

## Learnings

- Session store isn't thread-safe by default
- Need to check for race conditions in concurrent handlers

## Files Changed

- `auth/session.go`
- `auth/session_test.go`

## Links

- PR: #123
- Related spec: [specs/features/authentication.md](../specs/features/authentication.md)
```

**Archival:** Tasks older than 90 days move to `tasks/archive/YYYY-MM/`

#### `/conversations/` - Agent Collaboration

**Purpose:** When agents discuss/debate approaches

**Example:**
```markdown
# Conversation: Database Migration Strategy

**Date:** 2025-01-15
**Participants:** agent-1, agent-2, agent-3

## Context

We need to migrate from PostgreSQL to ClickHouse for analytics.

## Agent-1's Proposal

Use dual-write pattern during migration...

## Agent-2's Concerns

Dual-write can cause data inconsistency...

## Resolution

Agreed to use event sourcing approach...

## Action Items

- [ ] Agent-1: Implement event log
- [ ] Agent-2: Build ClickHouse consumer
- [ ] Agent-3: Create migration plan doc
```

#### `/plans/` - Active Plans

**Purpose:** In-progress planning documents

**Active plans:**
```
plans/
├── README.md                     # Lists active plans
├── q1-2025-roadmap.md           # Current quarter
├── database-migration.md         # Specific project plan
└── real-time-features.md        # Research/planning phase
```

**Archive flow:**
1. Plan is completed or obsolete
2. Extract key decisions → update `specs/` or `knowledge/decisions.md`
3. Move plan to `plans/archive/YYYY-MM/`
4. Update `plans/README.md`

**Example archive:**
```
plans/archive/
└── 2024-12/
    ├── api-v2-design.md         # Completed, decisions in specs/api-design.md
    └── graphql-evaluation.md    # Decided against, rationale in knowledge/decisions.md
```

#### `/knowledge/` - Accumulated Wisdom

**Purpose:** Quick reference for agents and humans

**Contents:**

**`knowledge/gotchas.md`:**
```markdown
# Known Gotchas

## Session Store Race Condition

**Problem:** Default session store isn't thread-safe
**Solution:** Use mutex lock or Redis
**Discovered:** 2025-01-15 by agent-1
**Related:** tasks/agent-1/2025-01-15-fix-login-bug.md
```

**`knowledge/decisions.md` (ADRs):**
```markdown
# Architecture Decision Records

## ADR-001: Why We Chose PostgreSQL Over MongoDB

**Date:** 2024-12-01
**Decided by:** agent-2, human review
**Status:** Accepted

**Context:** Need to choose database for user data...

**Decision:** PostgreSQL for ACID guarantees

**Consequences:**
- ✅ Strong consistency
- ❌ More complex schema changes
```

**`knowledge/onboarding.md`:**
```markdown
# Onboarding Guide

Auto-generated from specs and knowledge.

## Quick Start

1. Architecture overview: [specs/architecture/overview.md]
2. Key patterns: [specs/patterns/]
3. Common gotchas: [knowledge/gotchas.md]

## Recent Major Changes

- 2025-01-10: Migrated to PostgreSQL (see plans/archive/2024-12/db-migration.md)
- 2024-12-15: Added authentication (see specs/features/authentication.md)
```

### Auto-Generated Files

**`README.md` (root):**
```markdown
# AI Notes for MyProject

Auto-generated on 2025-01-15 14:30

## Recent Activity

- agent-1: Fixed login bug (#42)
- agent-2: Implemented dark mode (#45)
- agent-3: Refactored API handlers

## Active Plans

- Database migration to ClickHouse
- Real-time features research

## Quick Links

- [Specs](specs/)
- [Recent Tasks](tasks/)
- [Knowledge Base](knowledge/)
```

**`specs/README.md`:**
Auto-generated index of all specs with last updated dates.

## Workflow Examples

### Example 1: Agent Starts New Task

```bash
# 1. Dispatch task
agenttree start 1 42  # Issue #42

# Behind the scenes:
# - Creates: tasks/agent-1/2025-01-15-fix-login-bug.md (from template)
# - Copies issue details
# - Agent starts work
```

**Agent workflow:**
1. Read relevant specs in `specs/`
2. Check `knowledge/gotchas.md` for known issues
3. Work on task
4. Update task log in `tasks/agent-1/YYYY-MM-DD-*.md`
5. On completion:
   - Update relevant spec in `specs/`
   - Add any gotchas to `knowledge/gotchas.md`
   - Mark task as complete

### Example 2: Multiple Agents Collaborate

```bash
agenttree start 1 50  # Implement feature X
agenttree start 2 51  # Implement feature Y (depends on X)

# Agent-2 blocks on Agent-1
# Agent-2 creates: conversations/2025-01-15-feature-dependencies.md
# Agents discuss approach
# Agents update their task logs with agreed approach
```

### Example 3: Planning Phase

```bash
agenttree plan "Migrate to microservices"

# Creates: plans/microservices-migration.md
# Agents collaborate to fill it out
# When complete:
#   - Key decisions → knowledge/decisions.md
#   - Architecture changes → specs/architecture/
#   - Plan → plans/archive/2025-01/
```

## AgentTree Commands

```bash
# View recent activity
agenttree notes recent

# Search across all notes
agenttree notes search "authentication"

# View agent's task log
agenttree notes tasks agent-1

# View spec
agenttree notes spec features/authentication

# Archive old tasks (auto-runs monthly)
agenttree notes archive --older-than 90

# Generate onboarding doc (auto-updated)
agenttree notes generate-onboarding

# Update spec index (auto-runs on commit)
agenttree notes update-index
```

## Benefits of This Structure

1. **Clear Separation:**
   - Living docs (`specs/`) vs historical logs (`tasks/`)
   - Active plans vs archived plans

2. **Findability:**
   - Consistent naming
   - Auto-generated indices
   - Search across everything

3. **Reduces Noise:**
   - Task logs archived after 90 days
   - Plans archived when completed
   - Specs stay up-to-date (not duplicated)

4. **Collaboration:**
   - `conversations/` for agent-agent discussion
   - Specs are shared source of truth

5. **Onboarding:**
   - Humans can read `specs/` and `knowledge/`
   - New agents get context from accumulated learnings

6. **Audit Trail:**
   - Task logs show what agents did
   - Decisions logged with rationale
   - Plans show evolution of thinking
