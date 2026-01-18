# Distributed State Machine Analysis: AgentTree Architecture

## Current Architecture Overview

AgentTree implements a **file-based distributed state machine** spanning two hosts:
- **Agent host**: Container running AI tool (Claude, etc.) - handles implementation stages
- **Controller host**: Main machine - handles CI, PR creation, merges, approvals

### State Storage & Coordination

```
┌─────────────────────────────────────────────────────────────────┐
│                        Git Repository                           │
│                   (_agenttree/issues/*.yaml)                    │
│                                                                 │
│   issue.yaml                                                    │
│   ├── stage: "implement"                                        │
│   ├── substage: "code"                                          │
│   ├── history: [...]                                            │
│   └── controller_hooks_executed: "implementation_review"        │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ sync via git pull/push
                              │
        ┌─────────────────────┴─────────────────────┐
        │                                           │
        ▼                                           ▼
┌───────────────────┐                   ┌───────────────────┐
│   Agent (Container)│                   │  Controller (Host) │
│                   │                   │                   │
│  - Read state     │                   │  - Read state     │
│  - Execute work   │                   │  - Check CI       │
│  - Advance stage  │                   │  - Push branches  │
│  - Write state    │   (can't push)    │  - Create PRs     │
│  - Commit locally │ ◄───────────────► │  - Merge PRs      │
│                   │   host syncs      │  - Run hooks      │
└───────────────────┘                   └───────────────────┘
```

### Current Transition Flow

1. Agent calls `agenttree next`
2. `execute_exit_hooks()` validates current stage is complete
3. `update_issue_stage()` writes new state to YAML + commits
4. `execute_enter_hooks()` runs post-start hooks
5. Git sync propagates state to remote
6. Controller polls, sees state change, runs `check_controller_stages()`

### Pain Points Identified

| Issue | Impact |
|-------|--------|
| **Race conditions** | Multiple agents/controller modifying same state file |
| **Eventual consistency** | Git sync delays mean stale reads |
| **No transactional guarantees** | Exit hooks can fail after state written |
| **Lost updates** | Concurrent edits cause merge conflicts |
| **No rollback** | Failed transitions leave partial state |
| **Polling overhead** | Controller must poll git repo for changes |
| **Cross-host coordination** | Complex logic to determine who runs hooks |

---

## Alternative Approaches

### 1. Temporal.io (Workflow Orchestration)

**What it is**: Durable workflow execution platform with automatic retries, state persistence, and cross-service coordination.

```python
# Conceptual Temporal workflow for AgentTree
@workflow.defn
class IssueWorkflow:
    @workflow.run
    async def run(self, issue_id: str) -> str:
        # Each stage is a durable activity
        await workflow.execute_activity(
            run_define_stage, issue_id, start_to_close_timeout=timedelta(hours=1)
        )
        
        # Waits for human signal - durable across restarts
        await workflow.wait_condition(lambda: self.approved)
        
        await workflow.execute_activity(
            run_research_stage, issue_id, start_to_close_timeout=timedelta(hours=2)
        )
        # ... continues through stages
    
    @workflow.signal
    def approve(self):
        self.approved = True
```

**Pros**:
- Durable state with automatic replay/recovery
- Built-in human-in-the-loop via signals
- Handles retries, timeouts, versioning
- Strong consistency guarantees
- Excellent visibility/debugging tools

**Cons**:
- Requires running Temporal server (self-hosted or cloud)
- Overkill for local development scenario
- Learning curve for workflow concepts
- Adds infrastructure dependency

**Fit for AgentTree**: Medium-low. Temporal shines for cloud services, but AgentTree's local-first, git-based model doesn't align well. However, if AgentTree Cloud becomes a thing, Temporal would be excellent.

---

### 2. XState (Statecharts Library)

**What it is**: JavaScript/TypeScript library implementing statecharts with formal state machine semantics.

```typescript
// Conceptual XState machine for issue workflow
const issueMachine = createMachine({
  id: 'issue',
  initial: 'backlog',
  states: {
    backlog: {
      on: { START: 'define' }
    },
    define: {
      initial: 'draft',
      states: {
        draft: { on: { ADVANCE: 'refine' } },
        refine: { on: { ADVANCE: '#issue.define_review' } }
      }
    },
    define_review: {
      on: { 
        APPROVE: 'research',
        REJECT: 'define.draft'
      },
      meta: { requires: 'human' }
    },
    // ... more states
  }
});
```

**Pros**:
- Formal state machine with visualization tools
- Guards, actions, entry/exit handlers built-in
- Type-safe state transitions
- Can serialize/persist machine state
- Excellent for complex state logic

**Cons**:
- JavaScript/TypeScript ecosystem (AgentTree is Python)
- Single-process by design (distributed requires additional work)
- No built-in persistence (must implement)
- Doesn't solve cross-host coordination

**Fit for AgentTree**: Low. XState is excellent for single-process applications but doesn't address the distributed nature of the problem. A Python equivalent like `transitions` or `pytransitions` could help formalize the state machine logic locally.

---

### 3. Celery + Message Broker (Task Queue)

**What it is**: Distributed task queue with workers, message passing, and task dependencies.

```python
# Conceptual Celery tasks for AgentTree
@app.task(bind=True)
def run_implement_stage(self, issue_id: str):
    """Run in container worker"""
    # Do implementation work
    pass

@app.task(bind=True) 
def create_pr_task(self, issue_id: str):
    """Run on controller worker"""
    # Create PR on GitHub
    pass

# Chain tasks with callbacks
chain(
    run_implement_stage.s(issue_id),
    create_pr_task.s(issue_id),
    wait_for_approval.s(issue_id),  # Pauses until signal
).apply_async()
```

**Pros**:
- True distributed task execution
- Built-in retry, timeout, rate limiting
- Multiple worker types (agent vs controller)
- Task state tracking
- Mature, well-documented

**Cons**:
- Requires message broker (Redis/RabbitMQ)
- Tasks are point-in-time, not long-running workflows
- No native "wait for human" pattern
- State lives in broker, not in git
- More suited for stateless tasks than stateful workflows

**Fit for AgentTree**: Medium. Could handle the cross-host coordination but loses the git-based state model that enables offline work and version control of issue history.

---

### 4. Event Sourcing + CQRS

**What it is**: Store all state changes as immutable events; derive current state by replaying events.

```python
# Events instead of state mutations
events = [
    IssueCreated(id="001", title="Fix login", timestamp="2026-01-15T10:00:00Z"),
    StageAdvanced(id="001", from_stage="backlog", to_stage="define", timestamp="..."),
    HookExecuted(id="001", hook="lint", result="pass", timestamp="..."),
    StageAdvanced(id="001", from_stage="define", to_stage="research", timestamp="..."),
    PRCreated(id="001", pr_number=42, timestamp="..."),
    # ...
]

# Current state derived from events
def get_issue_state(issue_id: str) -> IssueState:
    events = event_store.get_events(issue_id)
    state = IssueState()
    for event in events:
        state = state.apply(event)
    return state
```

**Pros**:
- Complete audit trail (already have `history` field!)
- Can replay to any point in time
- Natural fit for git (append-only event log)
- Enables debugging "how did we get here?"
- Cross-host events can be merged

**Cons**:
- More complex to implement correctly
- Queries require event replay (or projections)
- Schema evolution requires care
- Doesn't inherently solve coordination

**Fit for AgentTree**: High potential. The existing `history` field is already a primitive event log. Making it the source of truth rather than derived data would enable better debugging, replay, and potentially conflict-free state merging.

---

### 5. Saga Pattern (Distributed Transactions)

**What it is**: Coordinate multi-step operations across services with compensating transactions on failure.

```python
# Saga for stage transition
class StageTransitionSaga:
    def execute(self, issue_id: str, to_stage: str):
        try:
            self.run_exit_hooks(issue_id)      # Step 1
            self.update_state(issue_id)        # Step 2
            self.run_enter_hooks(issue_id)     # Step 3
            self.sync_remote(issue_id)         # Step 4
        except StepFailed as e:
            self.compensate(e.step)  # Rollback completed steps
    
    def compensate(self, failed_step: int):
        if failed_step >= 4:
            self.unsync_remote()
        if failed_step >= 2:
            self.rollback_state()
        # Step 1 has no compensation needed
```

**Pros**:
- Handles partial failures gracefully
- Makes compensation explicit
- Works across services/hosts

**Cons**:
- Complex to implement correctly
- Compensations may not be possible (can't un-merge a PR)
- Requires saga coordinator

**Fit for AgentTree**: Medium. The concept of compensating actions is useful, but many AgentTree operations (PR merge, git push) aren't easily reversible. Better to prevent failures than compensate for them.

---

### 6. Actor Model (Akka/Orleans Style)

**What it is**: Each issue is an actor with isolated state, communicating via async messages.

```
┌──────────────────────────────────────────────────────────────────┐
│                        Actor System                              │
├──────────────────┬──────────────────┬──────────────────────────┤
│  Issue-001 Actor │  Issue-002 Actor │  Controller Actor        │
│  ┌────────────┐  │  ┌────────────┐  │  ┌────────────────────┐  │
│  │ state:     │  │  │ state:     │  │  │ - monitors issues  │  │
│  │  implement │  │  │  research  │  │  │ - handles CI       │  │
│  │            │  │  │            │  │  │ - manages PRs      │  │
│  └────────────┘  │  └────────────┘  │  └────────────────────┘  │
│       ▲          │       ▲          │         ▲                │
│       │ messages │       │          │         │                │
└───────┴──────────┴───────┴──────────┴─────────┴────────────────┘
```

**Pros**:
- Natural isolation per issue
- Message passing prevents race conditions
- Scales well
- Clear ownership of state

**Cons**:
- Requires actor runtime
- Persistence needs external implementation
- Overkill for typical use (1-10 concurrent issues)
- Doesn't solve cross-host distribution

**Fit for AgentTree**: Low. The actor model's benefits emerge at scale; AgentTree's typical workload is small enough that the complexity isn't justified.

---

## Recommended Approach: Evolutionary Improvements

Rather than adopting a heavyweight framework, I recommend **incremental improvements** to the current architecture:

### 1. Formalize the State Machine (Python `transitions`)

```python
from transitions import Machine

class IssueStateMachine:
    states = ['backlog', 'define', 'research', 'plan', 'implement', 'review', 'accepted']
    
    transitions = [
        {'trigger': 'start', 'source': 'backlog', 'dest': 'define', 'before': 'validate_dependencies'},
        {'trigger': 'advance', 'source': 'define', 'dest': 'research', 'conditions': 'problem_defined'},
        {'trigger': 'advance', 'source': 'research', 'dest': 'plan', 'conditions': 'research_complete'},
        # ...
    ]
    
    def __init__(self, issue: Issue):
        self.issue = issue
        self.machine = Machine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=issue.stage
        )
```

**Benefits**:
- Validates transitions are legal
- Centralizes state logic
- Provides visualization (graphviz export)
- Guards prevent invalid states

### 2. Event-Sourced History (Enhance Existing)

Make `history` authoritative rather than derived:

```python
# Current: state + derived history
issue.stage = "implement"
issue.history.append(HistoryEntry(...))

# Better: history is source of truth
def advance_stage(issue_id: str, event: StageEvent):
    """Append event, derive current state from events"""
    events = load_events(issue_id)
    events.append(event)
    save_events(issue_id, events)
    
    # Current state is projection
    current = project_state(events)
    save_state_cache(issue_id, current)  # For fast reads
```

**Benefits**:
- Complete audit trail
- Conflict resolution via event merging (not state merging)
- Can rebuild state from history
- Debugging: "show me everything that happened"

### 3. Optimistic Locking with Version Numbers

```yaml
# issue.yaml
version: 7  # Increment on each write
stage: implement
# ...
```

```python
def update_issue(issue_id: str, updates: dict, expected_version: int):
    issue = load_issue(issue_id)
    if issue.version != expected_version:
        raise ConcurrencyError("Issue modified by another process")
    
    issue.version += 1
    issue.update(updates)
    save_issue(issue)
```

**Benefits**:
- Detects concurrent modifications
- Enables retry logic
- Simple to implement

### 4. WebSocket-Based State Sync (Replace Polling)

Instead of git-based polling, use real-time sync for active sessions:

```
┌─────────────────┐          WebSocket          ┌─────────────────┐
│  Agent Container │ ◄────────────────────────► │  Controller     │
│                 │   state_changed events     │                 │
│  - Working on   │   hook_completed events    │  - Watching     │
│    implement    │   request_sync events      │    all issues   │
└─────────────────┘                            └─────────────────┘
```

**Benefits**:
- Immediate state propagation
- Reduced git sync frequency
- Can batch git syncs for durability
- Better UX (instant updates in web UI)

### 5. Controller as Coordinator (Clarify Ownership)

Make explicit which operations are controller-only:

```python
# Clear separation
CONTROLLER_ONLY_OPERATIONS = {
    'push_branch',
    'create_pr', 
    'merge_pr',
    'run_ci_check',
    'approve_transition',
}

AGENT_OPERATIONS = {
    'advance_substage',
    'write_output_file',
    'commit_changes',
}

# Controller hooks become explicit API calls
class ControllerAPI:
    @requires_controller_context
    def push_branch(self, issue_id: str): ...
    
    @requires_controller_context  
    def create_pr(self, issue_id: str): ...
```

---

## Comparison Matrix

| Approach | Complexity | Distributed | Durability | Offline | Fit |
|----------|-----------|-------------|------------|---------|-----|
| **Current (Git)** | Low | Via git | Git | ✅ | Baseline |
| **Temporal** | High | Native | Native | ❌ | Cloud only |
| **XState** | Medium | ❌ | Custom | ❌ | Wrong language |
| **Celery** | Medium | Native | Broker | ❌ | Loses git |
| **Event Sourcing** | Medium | Via git | Git | ✅ | Good fit |
| **Saga** | High | Custom | Custom | Partial | Partial fit |
| **Actor Model** | High | Custom | Custom | ❌ | Overkill |
| **Incremental** | Low | Via git | Git | ✅ | **Best fit** |

---

## Conclusion

AgentTree's architecture is reasonable for its constraints (local-first, git-based, offline-capable). The "state machine across hosts" pattern you've implemented is essentially a **choreography-based saga** using git as the message bus.

**Recommended next steps**:

1. **Short term**: Add optimistic locking (`version` field) to prevent lost updates
2. **Medium term**: Formalize state machine with `transitions` library for validation
3. **Medium term**: Enhance history to be event-sourced (enables better debugging)
4. **Longer term**: Consider WebSocket sync for real-time coordination (keep git for durability)

The current approach is pragmatic. The improvements above strengthen it without requiring infrastructure changes that would undermine the local-first, developer-friendly nature of AgentTree.
