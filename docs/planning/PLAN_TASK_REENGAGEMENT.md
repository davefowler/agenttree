# Plan: Task Re-engagement and Context Management

**Date:** 2026-01-04
**Status:** Planning
**Issue:** How to enable agents to resume work on tasks days later

## Problem Statement

Currently, agents cannot effectively re-engage with tasks after initial completion because:

1. **Context is cleared on every dispatch** - `reset_worktree()` does:
   - Hard reset to `origin/main`
   - Cleans all untracked files
   - Removes TASK.md
   - Destroys all local state

2. **No chat history is saved** - When an agent works on a task, the entire conversation with Claude Code/Aider is lost when:
   - Task completes
   - New task is dispatched
   - tmux session is killed

3. **No mechanism to resume PR work** - Common scenario:
   ```
   Agent-1 works on Issue #42
   → Creates PR #50
   → Moves to Issue #43 (branch changes, context cleared)
   → CI fails on PR #50
   → User wants Agent-1 to fix it
   → ❌ Agent has no memory of PR #50's context
   ```

4. **Uncertainty about organization** - Should we organize by:
   - Agent? (current: `agent-1`, `agent-2`, `agent-3`)
   - Task? (alternative: `task-42`, `task-43`, `task-44`)

5. **Multi-repo question** - Should one AgentTree instance:
   - Serve one repo (current)
   - Serve multiple repos (centralized agent pool)

## Current Behavior Analysis

### Verified: We DO reset to main on each dispatch

From `agenttree/worktree.py:102-150`:

```python
def reset_worktree(worktree_path: Path, base_branch: str = "main") -> None:
    # Fetch latest
    subprocess.run(["git", "fetch", "origin"], ...)

    # Checkout base branch
    subprocess.run(["git", "checkout", base_branch], ...)

    # Reset to origin
    subprocess.run(["git", "reset", "--hard", f"origin/{base_branch}"], ...)

    # Clean untracked files
    subprocess.run(["git", "clean", "-fd"], ...)

    # Remove TASK.md if it exists
    task_file = worktree_path / "TASK.md"
    if task_file.exists():
        task_file.unlink()
```

**Behavior:** Every `agenttree start` call completely wipes the worktree.

### What We Currently Track

In `_agenttree/` repository:
- ✅ **Task logs**: `_agenttree/tasks/agent-1/2026-01-04-fix-auth.md`
- ✅ **Specs**: `_agenttree/specs/features/issue-42.md`
- ✅ **Notes**: `_agenttree/notes/agent-1/findings.md`
- ❌ **Chat history**: Not saved
- ❌ **Task state**: No branch/PR tracking
- ❌ **Context dumps**: No conversation summaries

## Proposed Solutions

### Option 1: Task-Centric Organization (Persistent Task Worktrees)

**Concept:** Each task gets its own persistent worktree that survives across sessions.

```
~/Projects/worktrees/myapp/
├── task-42/              # Issue #42's worktree
│   ├── .git
│   ├── TASK.md
│   ├── CONTEXT.md        # Chat history / summary
│   └── <project files>
├── task-43/              # Issue #43's worktree
└── task-44/
```

**tmux sessions:** Named by task: `task-42`, `task-43`

**Workflow:**
```bash
# First time working on issue #42
agenttree start task-42 --issue 42
# Creates: task-42 worktree, task-42 tmux session
# Agent works, creates PR #50, closes session

# Days later, CI fails on PR #50
agenttree resume task-42
# Reopens: task-42 tmux session
# Loads: CONTEXT.md (chat summary or full history)
# Agent continues from where it left off
```

**Pros:**
- ✅ Natural task persistence
- ✅ Easy to resume any task
- ✅ Multiple agents can work on same task over time
- ✅ Context stays with the task
- ✅ Branch isolation (each task = one branch)

**Cons:**
- ❌ Worktrees accumulate over time (need cleanup strategy)
- ❌ Agent identity becomes less clear
- ❌ More complex worktree lifecycle management
- ❌ What if agent wants to work on 2 tasks simultaneously?

**Cleanup Strategy:**
```bash
# Auto-archive tasks when PR is merged
agenttree archive task-42
# Removes worktree, saves final state to _agenttree/ repo
```

---

### Option 2: Agent-Centric with Task State Management (Current + Enhancements)

**Concept:** Keep agent-based organization but add task state tracking.

```
~/Projects/worktrees/myapp/
├── agent-1/              # Agent-1's worktree
│   ├── .git
│   ├── TASK.md           # Current task
│   └── <project files>
├── agent-2/
└── agent-3/

_agenttree/
├── tasks/
│   └── agent-1/
│       ├── 2026-01-04-issue-42.md
│       └── 2026-01-04-issue-42-state.json  # NEW!
└── context/              # NEW!
    └── agent-1/
        └── issue-42-chat.md
```

**Task state file** (`issue-42-state.json`):
```json
{
  "issue_num": 42,
  "pr_num": 50,
  "branch": "agent-1/fix-auth-bug",
  "status": "pr_open",
  "last_active": "2026-01-04T10:30:00Z",
  "chat_history_path": "_agenttree/context/agent-1/issue-42-chat.md"
}
```

**Workflow:**
```bash
# First time working on issue #42
agenttree start 1 42
# Agent works, creates PR #50
# On completion: saves task state + chat history

# Days later, CI fails on PR #50
agenttree resume 1 --task 42
# Checks out PR branch: agent-1/fix-auth-bug
# Loads chat history: _agenttree/context/agent-1/issue-42-chat.md
# Agent continues work
```

**Pros:**
- ✅ Maintains agent identity (simpler mental model)
- ✅ Fixed number of worktrees (predictable resources)
- ✅ Agent can context-switch between tasks
- ✅ Less complex than task-centric

**Cons:**
- ❌ Need explicit task state management
- ❌ Agent can only work on one task at a time
- ❌ More manual context switching

---

### Option 3: Hybrid - Task Worktrees + Ephemeral Agents

**Concept:** Tasks are persistent, agents are just labels.

```
~/Projects/worktrees/myapp/
├── task-42/              # Persistent task worktree
│   ├── .assigned_to      # File: "agent-1"
│   └── CONTEXT.md
├── task-43/              # Assigned to agent-2
└── task-44/              # Assigned to agent-1 (second task)
```

**Agent assignment:**
```bash
# Dispatch task to any available agent
agenttree start --issue 42
# Finds available agent (agent-1), creates task-42 worktree
# Records: task-42 is assigned to agent-1

# Agent-1 can work on multiple tasks
agenttree start --issue 44
# Creates task-44 worktree, also assigned to agent-1

# Resume any task
agenttree resume --task 42
# Loads task-42 worktree with agent-1's session
```

**Pros:**
- ✅ Best of both worlds
- ✅ Flexible agent allocation
- ✅ Persistent task state
- ✅ Easy to parallelize (agent-1 works on task-42 and task-44)

**Cons:**
- ❌ Most complex implementation
- ❌ Harder to understand ("which agent am I?")
- ❌ Resource management more complex

---

## Chat History: How to Save & Restore Context

### Challenge: Tools Don't Save Chat History by Default

**Claude Code:**
- Uses conversation API
- No built-in export
- Context is session-based

**Aider:**
- Uses OpenAI/Anthropic APIs
- Can save chat in `.aider.chat.history.md` (if configured)
- Can resume from history file

### Solution A: Manual Context Dumps (Simple)

**On task completion**, agent creates a summary:

```bash
# In TASK.md or CONTEXT.md
## Task Summary (Auto-generated on completion)

### What Was Done
- Fixed authentication header bug
- Added JWT token refresh logic
- Updated tests in auth.test.ts

### Key Decisions
- Used localStorage for tokens (not cookies)
- 1-hour token expiry with refresh
- Added error boundary for auth failures

### Important Files
- src/auth/jwt.ts (main logic)
- src/api/client.ts (API client integration)
- tests/auth.test.ts (test coverage)

### Gotchas Discovered
- Token refresh needs to handle race conditions
- Cookies don't work with CORS in our setup

### For Future Work
- If re-engaging, start by reading auth.test.ts
- Check if token expiry time changed (was debated)
```

**How to create:**
```bash
# In dispatch workflow, before closing:
1. Agent creates PR
2. Agent appends summary to TASK.md
3. Agent commits: "Add task completion summary"
4. Save TASK.md to _agenttree/context/agent-1/issue-42-context.md
```

**On resume:**
```bash
# Load context into new TASK.md
cat _agenttree/context/agent-1/issue-42-context.md >> TASK.md
echo "\n\n## Resume Task\n\nCI failed with error: ..." >> TASK.md
```

**Pros:**
- ✅ Simple to implement
- ✅ Works with any tool (Claude Code, Aider, custom)
- ✅ Human-readable summaries

**Cons:**
- ❌ Agent must remember to create summary
- ❌ Not full chat history (lossy)
- ❌ Manual process (can forget)

---

### Solution B: Automatic Chat Export (Complex)

**For Aider:** Already supported via `.aider.chat.history.md`

**For Claude Code:** Would need to:
1. Hook into conversation API
2. Export full transcript on session end
3. Save to `_agenttree/context/agent-1/issue-42-chat.json`

**On resume:**
- Load chat history file
- Append to context or summarize with Claude

**Pros:**
- ✅ Complete history (lossless)
- ✅ Automatic (no manual work)

**Cons:**
- ❌ Tool-specific implementation
- ❌ Large files (entire conversations)
- ❌ May hit context limits on resume

---

### Solution C: Hybrid - Auto Summary + Manual Notes

**Automatic:**
- Agent creates structured summary in CONTEXT.md (required)
- Template enforces key sections

**Manual:**
- Agent adds notes/gotchas to _agenttree/notes/ (optional)
- Used for particularly tricky issues

**Implementation:**
```bash
# On task completion:
1. CLI prompts agent: "Create completion summary in CONTEXT.md"
2. Agent fills template:
   - What was done
   - Key files changed
   - Decisions made
   - How to resume
3. CLI saves CONTEXT.md to _agenttree/context/agent-1/issue-42.md
4. CLI saves task state JSON
```

**Pros:**
- ✅ Balances automation and flexibility
- ✅ Enforces documentation
- ✅ Human-readable

**Cons:**
- ❌ Requires discipline
- ❌ Still somewhat manual

---

## Multi-Repo Considerations

### Question: One AgentTree per repo, or one for all repos?

#### Option A: Per-Repo AgentTree (Current, Recommended)

**Architecture:**
```
~/Projects/
├── myapp/
│   ├── .agenttree.yaml
│   └── _agenttree/          # myapp-agents repo
└── another-app/
    ├── .agenttree.yaml
    └── _agenttree/          # another-app-agents repo

~/Projects/worktrees/
├── myapp/
│   ├── agent-1/
│   └── agent-2/
└── another-app/
    ├── agent-1/
    └── agent-2/
```

**Pros:**
- ✅ Simple isolation (no cross-contamination)
- ✅ Project-specific setup scripts
- ✅ Project-specific _agenttree/ repository
- ✅ Clear ownership (myapp agents work on myapp)
- ✅ Easier to understand and maintain

**Cons:**
- ❌ Duplicate agents (can't share pool)
- ❌ More resource usage (if using containers)

---

#### Option B: Central Agent Pool

**Architecture:**
```
~/.agenttree/
├── config.yaml
├── _agenttree/
│   ├── agent-1/
│   ├── agent-2/
│   └── agent-3/
└── worktrees/
    ├── myapp-task-42/
    ├── otherapp-task-10/
    └── myapp-task-43/
```

**config.yaml:**
```yaml
projects:
  - name: myapp
    repo: ~/Projects/myapp
    agents_repo: myapp-agents
  - name: otherapp
    repo: ~/Projects/otherapp
    agents_repo: otherapp-agents

agents:
  agent-1:
    current_task: myapp-task-42
  agent-2:
    current_task: otherapp-task-10
```

**Pros:**
- ✅ Share agents across projects
- ✅ Central management
- ✅ Better resource utilization

**Cons:**
- ❌ Much more complex
- ❌ Cross-project contamination risk
- ❌ Setup scripts become project-specific
- ❌ Harder to reason about
- ❌ Agents need project-switching logic

---

### Container Overhead Analysis

**If using Docker/Podman containers:**

**Idle container resource usage:**
- Memory: ~50-100MB per container (minimal)
- Disk: Shared layers (minimal)
- CPU: 0% when idle

**Per-repo overhead:**
- 3 agents = 3 containers = ~150-300MB RAM
- For 10 repos = 30 containers = ~1.5-3GB RAM

**Conclusion:** If you have 10+ repos, centralized might make sense. For <5 repos, per-repo is simpler.

**If using tmux sessions (current):**

**Idle tmux session resource usage:**
- Memory: ~5-10MB per session (negligible)
- CPU: 0% when idle

**Conclusion:** With tmux, per-repo overhead is negligible. Keep it simple.

---

## Recommendations

### 1. Organization: **Option 2 (Agent-Centric + Task State)**

**Reasoning:**
- Simpler mental model (agents have identity)
- Fixed resource usage (predictable)
- Easier to implement (incremental improvements)
- Agent can still work on multiple tasks (via state management)

**Changes needed:**
- Add task state tracking (`_agenttree/tasks/agent-1/issue-42-state.json`)
- Add `agenttree resume` command
- Save context summaries to `_agenttree/context/`

---

### 2. Chat History: **Solution C (Hybrid Auto + Manual)**

**Reasoning:**
- Balances automation with flexibility
- Works with any tool (Claude Code, Aider)
- Enforceable via CLI

**Implementation:**
- Add CONTEXT.md template
- CLI asks agent to fill it on completion
- Save to _agenttree/context/ automatically

---

### 3. Multi-Repo: **Option A (Per-Repo)**

**Reasoning:**
- Simple isolation
- Minimal overhead with tmux
- Clear ownership
- Easier to maintain

**Future:** If user has 10+ repos, revisit centralized approach.

---

## Implementation Plan

### Phase 1: Add Task State Tracking

**Files to create:**
- `agenttree/task_state.py` - TaskState model, save/load functions

**Changes:**
- `cli.py:dispatch()` - Create task state on dispatch
- `cli.py:dispatch()` - On PR creation, update state with PR number
- `agents_repo.py` - Add `save_task_state()` method

**Task state schema:**
```python
class TaskState(BaseModel):
    issue_num: int
    pr_num: Optional[int]
    branch: str
    status: str  # "in_progress", "pr_open", "completed"
    created_at: datetime
    last_active: datetime
    context_file: Optional[str]  # Path to context summary
```

---

### Phase 2: Add Context Summary Template

**Files to create:**
- `.agenttree/CONTEXT_TEMPLATE.md` - Template for completion summaries

**Template:**
```markdown
# Task Completion Summary: {issue_title}

**Issue:** #{issue_num}
**PR:** #{pr_num}
**Branch:** {branch}
**Completed:** {date}

## What Was Done

[Summary of changes made]

## Key Files Modified

- file1.ts - what changed
- file2.ts - what changed

## Decisions Made

- Why we chose approach X over Y
- Important architectural choices

## Gotchas Discovered

- Issue we hit and how we fixed it

## For Future Work / Resume

If you need to resume this task:
1. Start by reading {key_file}
2. Check {important_consideration}
3. Be aware of {gotcha}
```

**Changes:**
- `cli.py:dispatch()` - On task completion, prompt agent to fill CONTEXT.md
- Save to `_agenttree/context/agent-{num}/issue-{num}.md`

---

### Phase 3: Add Resume Command

**New command:**
```bash
agenttree resume AGENT_NUM --task ISSUE_NUM
# or
agenttree resume AGENT_NUM --pr PR_NUM
```

**Behavior:**
1. Load task state from `_agenttree/tasks/agent-1/issue-42-state.json`
2. Check out PR branch: `git checkout {branch}`
3. Load context summary: `cat _agenttree/context/agent-1/issue-42.md >> TASK.md`
4. Append new instructions: "CI failed with: {error}"
5. Restart tmux session with TASK.md

**Implementation:**
```python
@main.command()
@click.argument("agent_num", type=int)
@click.option("--task", type=int, help="Issue number to resume")
@click.option("--pr", type=int, help="PR number to resume")
def resume(agent_num: int, task: Optional[int], pr: Optional[int]):
    """Resume work on a previous task."""
    # Load task state
    # Checkout branch
    # Load context
    # Restart tmux
```

---

### Phase 4: Add Task Lifecycle Management

**New commands:**
```bash
agenttree tasks list           # List all tasks (active + archived)
agenttree tasks status 42      # Show status of task #42
agenttree tasks archive 42     # Archive completed task
agenttree tasks cleanup        # Remove old archived tasks
```

**Auto-archive on PR merge:**
- When PR merges, archive task automatically
- Move worktree to "archived" state (or remove)
- Keep context in _agenttree/ repo

---

## Open Questions

1. **Should we support multiple active tasks per agent?**
   - Current: Agent-1 works on one task at a time
   - Alternative: Agent-1 can have task-42 and task-44 in progress
   - Recommendation: Start with one-at-a-time, add multi-task later if needed

2. **How long to keep task state?**
   - Keep indefinitely?
   - Auto-delete after 30 days of inactivity?
   - Recommendation: Keep until PR is merged + 7 days

3. **Should context summaries be required or optional?**
   - Required: Enforces documentation, easier to resume
   - Optional: More flexible, but risky
   - Recommendation: Required for PR creation

4. **Integration with Claude Code context limits?**
   - If CONTEXT.md is very long, may hit limits
   - Solution: Summarize with Claude before loading
   - Or: Just load last N messages

---

## Success Criteria

After implementation, the following should work:

```bash
# Day 1: Agent-1 works on issue #42
agenttree start 1 42
# Agent creates PR #50, fills CONTEXT.md, closes

# Day 3: CI fails on PR #50
agenttree resume 1 --pr 50
# Agent sees:
# - Previous context summary
# - CI failure details
# - Exact branch state
# Agent fixes issue, pushes

# Week later: Need to make related change to issue #42 work
agenttree resume 1 --task 42
# Agent reloads full context, continues
```

**Validation:**
- ✅ Agent can resume any previous task
- ✅ Context is preserved across sessions
- ✅ No confusion about "where was I?"
- ✅ Works days/weeks later

---

## Timeline (Rough Estimate)

- **Phase 1:** Task State Tracking - ~4 hours
- **Phase 2:** Context Summaries - ~2 hours
- **Phase 3:** Resume Command - ~3 hours
- **Phase 4:** Task Lifecycle - ~3 hours

**Total:** ~12 hours of development

---

## Alternative: Defer to Future

**Minimal viable approach** (if we want to ship sooner):

1. **Manual process:** Document in AGENT_GUIDE.md:
   ```
   When completing a task:
   1. Create _agenttree/context/agent-{num}/issue-{num}.md
   2. Document what you did, key files, decisions
   3. Commit to _agenttree/ repo

   When resuming:
   1. Read _agenttree/context/agent-{num}/issue-{num}.md
   2. Check out your PR branch
   3. Continue work
   ```

2. **No CLI support yet**, just documentation

3. **Rely on agent discipline** to document well

**Pros:**
- ✅ Ships immediately
- ✅ Validates approach before building

**Cons:**
- ❌ Easy to forget
- ❌ Inconsistent documentation
- ❌ Manual process is error-prone

---

## Decision Required

**Before implementing, please confirm:**

1. **Organization approach:** Agent-centric (Option 2)?
2. **Chat history approach:** Hybrid manual+auto (Solution C)?
3. **Multi-repo approach:** Per-repo (Option A)?
4. **Timeline:** Implement now, or defer to manual process first?

I recommend: **Start with manual process (defer)**, validate with real usage, then build CLI support in Phase 2.
