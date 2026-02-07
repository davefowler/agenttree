# API Consolidation Plan

## Overview

This document outlines a plan to consolidate duplicated logic scattered across `cli.py`, `hooks.py`, `actions.py`, `web/app.py`, and other modules into a clean, centralized API layer. The goal is to make the codebase more maintainable, reduce bugs from inconsistent implementations, and provide a single source of truth for common operations.

## Current Problems

### 1. Multiple Issue Classes

We have **three different Issue models** plus a conversion function:

| Location | Class | Purpose |
|----------|-------|---------|
| `issues.py:52` | `Issue` | Core data model from YAML |
| `web/models.py:44` | `Issue` | Web API response model |
| `github.py:13` | `Issue` | GitHub issue (different domain, OK) |
| `web/app.py:280` | `convert_issue_to_web()` | Converts between them |

**Problem**: `WebIssue` duplicates fields from core `Issue` and adds computed properties like `tmux_active`, `has_worktree`, `port`. This logic should live on the core Issue.

### 2. Duplicated Cleanup Logic

The same "parking lot" cleanup patterns appear in **three files**:

```python
# Pattern repeated in cli.py (lines 3395-3498), hooks.py (lines 2564-2672)
if config.is_parking_lot(issue.stage):
    # Cleanup worktrees, branches, sessions...
```

This means any bug fix or behavior change must be applied to multiple places.

### 3. Agent Start/Stop Logic Scattered

Agent lifecycle management is spread across:

| File | Functions |
|------|-----------|
| `cli.py` | `start_agent()`, `stop()`, `stop_all()` |
| `state.py` | `stop_agent()`, `stop_all_agents_for_issue()`, `cleanup_*()` |
| `actions.py` | `start_manager()`, `auto_start_agents()`, `stop_all_agents()` |
| `web/app.py` | `start_issue()`, `stop_issue()` |
| `tmux.py` | `AgentManager.start_agent()`, `.stop_agent()`, etc. |

**Problem**: Different entry points have subtly different behaviors (timeouts, cleanup, error handling).

### 4. Session Management Inconsistencies

Tmux session naming and checking happens in multiple places:
- `config.py`: `get_issue_tmux_session()`, `get_manager_tmux_session()`, `is_project_session()`
- `tmux.py`: `session_exists()`, `list_sessions()`, `list_issue_sessions()`
- `state.py`: `_get_tmux_sessions()`, `get_active_agent()`
- `web/app.py`: `_check_issue_tmux_session()`

### 5. Heartbeat in Wrong Location

The heartbeat loop (`web/app.py:61-93`) is web-server startup code mixed with domain logic. It should be a separate module that can be started independently.

### 6. Issue Filtering/Sorting in Web Only

Functions like `filter_issues()`, `_filter_flow_issues()`, `_sort_flow_issues()` in `web/app.py` are general-purpose and should be available to CLI and other consumers.

## Proposed Solution: `agenttree/api.py`

Create a central API module that provides:

1. **A unified Issue interface** with computed properties
2. **Single implementations** of common operations
3. **Clean abstractions** over tmux/container/state

### New Module Structure

```
agenttree/
├── api.py           # NEW: Central API (high-level operations)
├── heartbeat.py     # NEW: Heartbeat loop extracted from web/app.py
├── issues.py        # Keep: Core Issue model, CRUD operations
├── config.py        # Keep: Configuration and naming conventions  
├── tmux.py          # Keep: Low-level tmux operations
├── state.py         # Keep: Agent state queries (simplify)
├── container.py     # Keep: Container runtime abstraction
├── hooks.py         # Simplify: Call api.py for complex operations
├── actions.py       # Simplify: Call api.py for complex operations
├── cli.py           # Simplify: Call api.py for complex operations
└── web/
    ├── app.py       # Simplify: Call api.py, remove domain logic
    └── models.py    # Simplify: Use Issue from api.py
```

---

## Detailed Changes

### Phase 1: Create `api.py` with Rich Issue Object

Create `agenttree/api.py` that provides a single `Issue` class with all computed properties:

```python
# agenttree/api.py
"""Central API for AgentTree operations.

This module provides a unified interface for working with issues, agents,
and sessions. All other modules (cli, web, hooks) should use this API
instead of directly accessing lower-level modules.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from agenttree import issues as issue_crud
from agenttree.config import load_config, AgentTreeConfig
from agenttree import tmux


@dataclass
class Issue:
    """Rich issue object with computed properties.
    
    This is the canonical Issue representation used throughout AgentTree.
    It combines data from issue.yaml with runtime state (tmux, worktree).
    """
    # Core data (from issue.yaml)
    id: str
    slug: str
    title: str
    stage: str
    substage: str | None
    priority: str
    created: str
    updated: str
    labels: list[str]
    dependencies: list[str]
    pr_url: str | None
    pr_number: int | None
    worktree_dir: str | None
    branch: str | None
    
    # Computed properties
    tmux_active: bool
    has_worktree: bool
    port: int | None
    
    @property
    def is_parking_lot(self) -> bool:
        """Check if issue is in a parking lot stage."""
        config = load_config()
        return config.is_parking_lot(self.stage)
    
    @property
    def is_terminal(self) -> bool:
        """Check if issue is in a terminal stage (accepted, not_doing)."""
        return self.stage in ("accepted", "not_doing")
    
    @property
    def is_review_stage(self) -> bool:
        """Check if issue is in a human review stage."""
        config = load_config()
        stage = config.get_stage(self.stage)
        return stage.human_review if stage else False


def get_issue(issue_id: str, check_runtime: bool = True) -> Issue | None:
    """Get a single issue with optional runtime state.
    
    Args:
        issue_id: Issue ID (can be "42" or "042")
        check_runtime: If True, also check tmux session status
        
    Returns:
        Issue object or None if not found
    """
    raw = issue_crud.get_issue(issue_id)
    if not raw:
        return None
    return _enrich_issue(raw, check_runtime)


def list_issues(
    sync: bool = False,
    check_runtime: bool = True,
    stage: str | None = None,
    exclude_parking_lot: bool = False,
) -> list[Issue]:
    """List issues with optional filtering and runtime state.
    
    Args:
        sync: If True, sync git before listing
        check_runtime: If True, check tmux session status for each issue
        stage: If provided, filter to issues in this stage
        exclude_parking_lot: If True, exclude parking lot stages
        
    Returns:
        List of Issue objects
    """
    config = load_config()
    raw_issues = issue_crud.list_issues(sync=sync)
    
    # Filter by stage
    if stage:
        raw_issues = [i for i in raw_issues if i.stage == stage]
    
    # Exclude parking lot
    if exclude_parking_lot:
        raw_issues = [i for i in raw_issues if not config.is_parking_lot(i.stage)]
    
    return [_enrich_issue(i, check_runtime) for i in raw_issues]


def filter_issues(issues: list[Issue], search: str | None) -> list[Issue]:
    """Filter issues by search query.
    
    Matches against issue ID, title, and labels (case-insensitive).
    """
    if not search or not search.strip():
        return issues
    
    query = search.lower().strip()
    return [
        i for i in issues
        if query in i.id
        or query in i.title.lower()
        or any(query in label.lower() for label in i.labels)
    ]


def sort_issues(
    issues: list[Issue],
    by: str = "priority",
    reverse: bool = False,
) -> list[Issue]:
    """Sort issues by field.
    
    Args:
        issues: List of issues to sort
        by: Sort key ("priority", "created", "updated", "id")
        reverse: If True, reverse sort order
    """
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    
    if by == "priority":
        key = lambda i: priority_order.get(i.priority, 99)
    elif by == "created":
        key = lambda i: i.created
    elif by == "updated":
        key = lambda i: i.updated
    else:
        key = lambda i: i.id
    
    return sorted(issues, key=key, reverse=reverse)


# ============================================================================
# Agent Lifecycle
# ============================================================================

def start_agent(issue_id: str, role: str = "developer", skip_preflight: bool = False) -> bool:
    """Start an agent for an issue.
    
    Args:
        issue_id: Issue to start agent for
        role: Agent role ("developer", "reviewer", etc.)
        skip_preflight: Skip preflight checks
        
    Returns:
        True if agent started successfully
    """
    # Implementation calls existing logic in state.py/tmux.py
    # Single source of truth for "how to start an agent"
    pass


def stop_agent(issue_id: str, role: str = "developer") -> bool:
    """Stop an agent for an issue.
    
    Handles tmux session and container cleanup.
    
    Args:
        issue_id: Issue to stop agent for  
        role: Agent role to stop
        
    Returns:
        True if agent was running and stopped
    """
    # Implementation consolidates logic from state.py/cli.py
    pass


def stop_all_agents(include_manager: bool = False) -> int:
    """Stop all running agents.
    
    Args:
        include_manager: If True, also stop the manager agent
        
    Returns:
        Number of agents stopped
    """
    # Implementation consolidates logic from actions.py/cli.py
    pass


def is_agent_running(issue_id: str, role: str = "developer") -> bool:
    """Check if an agent is running for an issue.
    
    This is the canonical way to check agent status.
    Uses tmux session existence as source of truth.
    """
    config = load_config()
    session_name = config.get_issue_tmux_session(issue_id, role)
    return tmux.session_exists(session_name)


# ============================================================================
# Stage Transitions
# ============================================================================

def advance_issue(issue_id: str, user: str | None = None) -> bool:
    """Advance an issue to the next stage (approve).
    
    Used when human approves at a review stage.
    Runs exit/enter hooks.
    
    Args:
        issue_id: Issue to advance
        user: User performing the approval
        
    Returns:
        True if advanced successfully
    """
    pass


def move_issue(issue_id: str, target_stage: str) -> bool:
    """Move an issue to a specific stage.
    
    Used for redirects (e.g., back to implementation after review).
    Runs appropriate hooks.
    
    Args:
        issue_id: Issue to move
        target_stage: Target stage name
        
    Returns:
        True if moved successfully
    """
    pass


# ============================================================================
# Cleanup Operations  
# ============================================================================

def cleanup_stale_worktrees() -> int:
    """Clean up worktrees for parking lot issues.
    
    Returns:
        Number of worktrees cleaned up
    """
    pass


def cleanup_stale_sessions() -> int:
    """Clean up tmux sessions without matching issues.
    
    Returns:
        Number of sessions cleaned up
    """
    pass


def cleanup_stale_containers() -> int:
    """Clean up containers without matching sessions.
    
    Returns:
        Number of containers cleaned up
    """
    pass


def cleanup_all() -> dict[str, int]:
    """Run all cleanup operations.
    
    Returns:
        Dict with counts: {"worktrees": N, "sessions": N, "containers": N}
    """
    return {
        "worktrees": cleanup_stale_worktrees(),
        "sessions": cleanup_stale_sessions(),
        "containers": cleanup_stale_containers(),
    }


# ============================================================================
# Private Helpers
# ============================================================================

def _enrich_issue(raw: issue_crud.Issue, check_runtime: bool) -> Issue:
    """Convert raw issue to rich Issue with computed properties."""
    config = load_config()
    
    tmux_active = False
    if check_runtime:
        session_name = config.get_issue_tmux_session(raw.id, "developer")
        tmux_active = tmux.session_exists(session_name)
    
    return Issue(
        id=raw.id,
        slug=raw.slug,
        title=raw.title,
        stage=raw.stage,
        substage=raw.substage,
        priority=raw.priority.value,
        created=raw.created,
        updated=raw.updated,
        labels=raw.labels,
        dependencies=raw.dependencies,
        pr_url=raw.pr_url,
        pr_number=raw.pr_number,
        worktree_dir=raw.worktree_dir,
        branch=raw.branch,
        tmux_active=tmux_active,
        has_worktree=bool(raw.worktree_dir),
        port=config.get_port_for_issue(raw.id),
    )
```

### Phase 2: Extract Heartbeat to Own Module

Create `agenttree/heartbeat.py`:

```python
# agenttree/heartbeat.py
"""Heartbeat system for automatic issue monitoring.

This module provides periodic checks and actions that keep the
AgentTree system running smoothly.
"""

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta

from rich.console import Console

console = Console()


class Heartbeat:
    """Configurable heartbeat that runs periodic checks."""
    
    def __init__(
        self,
        interval_seconds: int = 60,
        on_tick: Callable[[], None] | None = None,
    ):
        self.interval = interval_seconds
        self.on_tick = on_tick
        self._running = False
        self._last_tick: datetime | None = None
    
    async def start(self) -> None:
        """Start the heartbeat loop."""
        self._running = True
        while self._running:
            try:
                self._last_tick = datetime.now()
                if self.on_tick:
                    self.on_tick()
            except Exception as e:
                console.print(f"[red]Heartbeat error: {e}[/red]")
            await asyncio.sleep(self.interval)
    
    def stop(self) -> None:
        """Stop the heartbeat loop."""
        self._running = False


def default_heartbeat_tick() -> None:
    """Default heartbeat action: check stalled agents, cleanup orphans."""
    from agenttree import api
    
    # Check for stalled agents
    issues = api.list_issues(check_runtime=True, exclude_parking_lot=True)
    for issue in issues:
        if not issue.tmux_active:
            console.print(f"[yellow]Issue #{issue.id} has no active agent[/yellow]")
```

### Phase 3: Update Consumers to Use API

#### Update `web/app.py`

Before:
```python
from agenttree import issues as issue_crud
from agenttree.web.models import Issue as WebIssue
# ... lots of conversion and filtering logic
```

After:
```python
from agenttree import api
# Use api.list_issues(), api.get_issue(), api.filter_issues() directly
```

Remove:
- `convert_issue_to_web()` function
- `filter_issues()` function (use `api.filter_issues()`)
- `_check_issue_tmux_session()` function (use `api.is_agent_running()`)
- `_sort_flow_issues()` / `_filter_flow_issues()` (use `api.sort_issues()`, `api.filter_issues()`)

#### Update `cli.py`

Replace direct imports and duplicated logic:

```python
# Before (scattered across cli.py)
from agenttree.issues import list_issues, get_issue
from agenttree.state import stop_agent, get_active_agent
from agenttree.tmux import session_exists
# ... lots of inline logic

# After
from agenttree import api
# Use api.start_agent(), api.stop_agent(), api.cleanup_all(), etc.
```

#### Update `hooks.py`

The cleanup logic (lines 2564-2672) should call `api.cleanup_stale_worktrees()` etc. instead of reimplementing.

#### Update `actions.py`

`stop_all_agents()` should call `api.stop_all_agents()`.

### Phase 4: Simplify `web/models.py`

The `Issue` class in `web/models.py` can be simplified or replaced:

```python
# Option A: Inherit from api.Issue for Pydantic serialization
from agenttree.api import Issue as CoreIssue
from pydantic import BaseModel

class Issue(BaseModel, CoreIssue):
    """Web-serializable issue."""
    pass

# Option B: Just use api.Issue directly and configure FastAPI
# to serialize dataclasses
```

---

## Migration Strategy

### Step 1: Create `api.py` (non-breaking)
- Create the new module with implementations
- Test that it works correctly
- Don't change any consumers yet

### Step 2: Add deprecation warnings
- Mark old functions as deprecated
- Log when old codepaths are used
- Verify production behavior unchanged

### Step 3: Migrate consumers one at a time
- Start with `web/app.py` (easiest to test)
- Then `actions.py` (used by heartbeat)
- Then `hooks.py` (complex but well-tested)
- Finally `cli.py` (largest file)

### Step 4: Remove deprecated code
- Delete `convert_issue_to_web()`, duplicate filters, etc.
- Remove deprecation warnings
- Update docs

---

## What Goes in the API

### Include in `api.py`:

| Function | Replaces |
|----------|----------|
| `get_issue()` | `issues.get_issue()` + runtime enrichment |
| `list_issues()` | `issues.list_issues()` + filtering + runtime |
| `filter_issues()` | `web/app.py:filter_issues()` |
| `sort_issues()` | `web/app.py:_sort_flow_issues()` |
| `start_agent()` | Logic in `cli.py`, `state.py`, `tmux.py` |
| `stop_agent()` | Logic in `cli.py`, `state.py` |
| `stop_all_agents()` | `actions.py:stop_all_agents()` |
| `is_agent_running()` | Various `session_exists()` checks |
| `advance_issue()` | `cli.py:approve_issue()` core logic |
| `move_issue()` | Stage transition logic |
| `cleanup_stale_*()` | Duplicated cleanup in hooks/cli |
| `send_message()` | `tmux.send_keys()` wrapper |

### Keep in existing modules:

| Module | Keep |
|--------|------|
| `issues.py` | Raw CRUD, YAML parsing, `Issue` dataclass |
| `config.py` | Configuration loading, naming conventions |
| `tmux.py` | Low-level tmux operations |
| `container.py` | Container runtime abstraction |
| `state.py` | Low-level state queries (simplify) |
| `hooks.py` | Hook execution (call api for logic) |

---

## File Size Impact

Current large files:
- `cli.py`: 3938 lines
- `hooks.py`: 2724 lines
- `web/app.py`: 1292 lines

Expected after refactoring:
- `cli.py`: ~2500 lines (remove duplicated logic)
- `hooks.py`: ~2000 lines (remove duplicated cleanup)
- `web/app.py`: ~800 lines (remove conversion/filtering)
- `api.py`: ~500 lines (new, consolidated)
- `heartbeat.py`: ~100 lines (new, extracted)

---

## Benefits

1. **Single source of truth** for agent lifecycle operations
2. **Consistent behavior** across CLI, web, and hooks
3. **Easier testing** - test api.py once instead of 5 places
4. **Cleaner imports** - consumers just `from agenttree import api`
5. **Better separation** - web layer only handles HTTP, not domain logic
6. **Reduced bugs** - fix once, works everywhere

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking changes | Migrate incrementally, keep old functions during transition |
| Performance | API functions should be thin wrappers, not add overhead |
| Circular imports | api.py imports from issues/tmux/config, they don't import from api |
| Test coverage gaps | Write tests for api.py before removing old code |

---

## Next Steps

1. [ ] Review and approve this plan
2. [ ] Create `api.py` skeleton with type hints
3. [ ] Implement `get_issue()` and `list_issues()` with tests
4. [ ] Extract heartbeat to `heartbeat.py`
5. [ ] Migrate `web/app.py` to use api
6. [ ] Migrate `actions.py` to use api
7. [ ] Migrate `hooks.py` cleanup to use api
8. [ ] Migrate `cli.py` to use api
9. [ ] Remove deprecated code
10. [ ] Update documentation
