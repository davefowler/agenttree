# AgentTree Concurrency Design

This document explains why many apparent "race conditions" are non-issues by design.

## Core Design Principles

### 1. Sharded Write Access

**Agents only write to their own issue folder.**

Each agent works in isolation:
- Agent working on issue 073 only writes to `_agenttree/issues/073-*/`
- Agent never writes to another agent's issue folder
- Agent never writes to shared config files

**Controller writes are staged-gated.**

The controller (host) only writes to issue.yaml during:
- `implementation_review` stage (human gate - agent paused)
- `accepted` stage (terminal - agent cleaned up)
- Initial issue creation (no agent yet)

### 2. Human Review Gates Create Natural Synchronization Points

```
Agent runs → hits plan_review → PAUSED (waiting for human)
                                 ↓
            Host can safely write during human review
                                 ↓
Human approves → Agent resumes
```

The agent cannot be actively writing when:
- It's at `plan_review` (blocked, waiting for approval)
- It's at `implementation_review` (blocked, waiting for approval)
- It's at `accepted` or `not_doing` (terminal, agent cleaned up)

### 3. Single Writer for _agenttree Sync

Only ONE process manages `_agenttree` git operations:
- The host's `sync_agents_repo()` function
- Protected by `.sync.lock` file lock
- Agents in containers don't have git remote access

This means:
- No merge conflicts in `_agenttree` repository
- No concurrent push/pull races
- All sync operations are serialized

## File Write Patterns

### issue.yaml

| Writer | When | Agent State |
|--------|------|-------------|
| Host: `create_issue()` | Issue creation | No agent |
| Host: `update_issue_stage()` | Stage transitions | Usually paused at gate |
| Host: `_update_issue_stage_direct()` | PR merged externally | **Paused at implementation_review** |
| Host: `assign_agent()` | Agent assignment | Starting up |
| Agent: Never | - | - |

**Why it's safe:** Agent never writes issue.yaml. Controller only writes during creation or at human review gates when agent is paused.

### .agent_session.yaml

| Writer | When | Agent State |
|--------|------|-------------|
| Agent: `save_session()` | After stage advance | Running |
| Host: `create_session()` | On restart | Agent restarting |
| Host: `delete_session()` | On kill | Agent being killed |

**Why it's safe:** File is per-issue. Only the assigned agent and the host managing that specific issue interact with it. Conflicts are rare and recoverable.

### state.yaml

| Writer | When | Protection |
|--------|------|------------|
| Any: `register_agent()` | Agent start | **FileLock** |
| Any: `unregister_agent()` | Agent stop | **FileLock** |
| Any: `allocate_port()` | Port assignment | **FileLock** |
| Any: `free_port()` | Port release | **FileLock** |

**Why it's safe:** All operations protected by `state.yaml.lock` with 5-second timeout.

### .agenttree.yaml (config)

| Writer | When | Agent State |
|--------|------|-------------|
| Human only | Manual edits | N/A |

**Why it's safe:** Only edited manually, not by automated processes.

## Why Multi-Machine Would Still Be Safe

Even when running on multiple machines (future):

1. **Issue sharding still applies** - Each agent still only writes to its own issue folder
2. **Git handles the rest** - `_agenttree` changes would go through git merge, and since different agents modify different files, merges are clean
3. **Rare conflicts are recoverable** - Worst case, a yaml file needs manual resolution

## Non-Issues (Removed from Edge Case Tracking)

These were identified as potential race conditions but are non-issues by design:

| "Issue" | Why It's Not |
|---------|--------------|
| Concurrent issue.yaml writes | Agent never writes; controller writes at gates |
| Merge conflicts in _agenttree | Single sync process; agents can't push |
| Two agents same file | Agents are sharded by issue |
| Controller/agent race | Human gates synchronize them |

## Actual Issues to Track

| Issue | Status | Notes |
|-------|--------|-------|
| Port exhaustion (infinite loop) | TODO | `allocate_port()` has no max limit |
| CI failure handling | TODO | Need feedback loop to agent |
| Circular dependency detection | TODO | Not validated |

## Recommendations

### Don't Add
- ❌ Per-file locks for issue.yaml (not needed - staged access)
- ❌ Distributed locking (overkill for current design)
- ❌ YAML write queues (complexity without benefit)

### Do Consider (Future)
- Add max port limit to prevent infinite loop
- Add CI status polling with agent notification
- Validate no circular dependencies on issue create
