# AgentTree Workflow - Critical Path

**Status:** Ready for Implementation
**Branch:** `claude/implement-spec-tdd-AoiCs`
**Last Updated:** 2026-01-11

---

## MVP Goal

Get to dogfooding: use agenttree to manage agenttree development.

**Critical Path:**
1. Issue CRUD CLI (`agenttree issue create/list/show`)
2. That's it. Everything else is tracked as agenttree issues.

---

## Current State

`.agenttrees/` directory is set up with:
- 10 issues filed (001-010)
- Templates for problem.md, plan.md
- Skills for each stage
- Config with validation rules

**Issue Status:**
| ID | Title | Stage |
|----|-------|-------|
| 001 | Issue CRUD CLI | research/plan (CRITICAL) |
| 002 | Stage transitions | problem_review |
| 003 | Web UI issues | problem_review |
| 004 | Validation system | backlog |
| 005 | CI integration | backlog |
| 006 | Code review API | backlog |
| 007 | GitHub sync | backlog |
| 008 | Changelog tab | backlog |
| 009 | Auto-dispatch | backlog |
| 010 | Post-merge docs | backlog |

---

## Issue #001: Issue CRUD CLI (Critical)

### What We Need

```bash
agenttree issue create <title> [--priority <p>]
    # Creates issue dir, issue.yaml, problem.md from template

agenttree issue list [--stage <stage>] [--json]
    # Lists issues from .agenttrees/issues/

agenttree issue show <id>
    # Shows issue details
```

### Implementation Plan

1. Create `agenttree/issues.py` with:
   - `Issue` Pydantic model matching issue.yaml schema
   - `create_issue(title, priority)` → creates dir + files
   - `list_issues(stage=None)` → returns list of Issues
   - `get_issue(id)` → returns single Issue

2. Add to `agenttree/cli.py`:
   - `@cli.group() def issue()` command group
   - `@issue.command() def create()`
   - `@issue.command() def list()`
   - `@issue.command() def show()`

3. Tests in `tests/unit/test_issues.py`

### Issue.yaml Schema

```yaml
id: "001"
slug: issue-crud-cli
title: "Implement issue CRUD CLI commands"
created: "2026-01-11T12:00:00Z"
updated: "2026-01-11T12:00:00Z"

stage: research  # backlog|problem|problem_review|research|plan_review|implement|implementation_review|accepted|not_doing
substage: plan   # depends on stage

assigned_agent: null  # or agent number
branch: null          # or branch name

labels: [critical, cli]
priority: critical  # low|medium|high|critical

github_issue: null  # optional link to GH issue

history:
  - stage: backlog
    timestamp: "2026-01-11T12:00:00Z"
```

---

## Directory Structure

```
.agenttrees/                    # Separate git repo (agenttree-agenttree)
├── issues/
│   ├── 001-issue-crud-cli/
│   │   ├── issue.yaml
│   │   ├── problem.md
│   │   └── plan.md
│   ├── 002-stage-transitions/
│   └── ...
├── templates/
│   ├── problem.md
│   └── plan.md
├── skills/
│   ├── problem.md
│   ├── research.md
│   └── implement.md
├── config.yaml
└── archive/
```

---

## After MVP

Once `agenttree issue create/list/show` works:
1. Move issue 001 to `accepted`
2. Start working on issues 002 and 003
3. Use `agenttree issue create` to file any new issues
4. We're dogfooding!

---

## Full Documentation

See `SESSION_SUMMARY.md` for complete architectural decisions including:
- Stage definitions and substages
- Validation rules
- Context layers (general, agenttree, stage, agent, task)
- All planned CLI commands
- Web UI design
