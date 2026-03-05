# AgentTree Roadmap

**Last Updated:** 2026-01-01
**Current Phase:** End of Phase 2

## Vision

AgentTree enables **parallel AI development** by orchestrating multiple AI coding agents across isolated git worktrees. Each phase builds toward a complete system for local, open-source, multi-agent software development.

## Phase Overview

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6
  Core     Docs      GitHub    Remote     Web       Memory
  ✅        ✅         🎯         ⏸️         ⏸️         ⏸️
```

---

## ✅ Phase 1: Core Package (COMPLETE)

**Duration:** Initial development
**Status:** Complete and tested

### Implemented Features

#### Configuration Management
- `Config` model with Pydantic validation
- YAML file parsing (`.agenttree.yaml`)
- Default values and project structure
- Port range allocation per agent
- Tool configuration (Claude, Aider, custom)

**Coverage:** 96%

#### Git Worktree Operations
- Create/remove worktrees for agents
- Reset worktrees to main branch
- Busy detection (uncommitted changes, active tasks)
- Worktree listing and status

**Coverage:** 88%

#### Tmux Session Management
- Create named sessions per agent
- Attach/detach from sessions
- Send commands to running agents
- Session existence checking
- Clean session termination

**Coverage:** 0% (integration test territory)

#### Agent Adapters
- `BaseAgent` interface
- Claude Code adapter
- Aider adapter
- Custom tool support

**Coverage:** 0% (needs tests)

#### CLI Foundation
- `agenttree init` - Initialize project
- `agenttree setup <agents>` - Create worktrees
- `agenttree start <agent> <issue>` - Assign work
- `agenttree status` - View all agents
- `agenttree attach <agent>` - Connect to session
- `agenttree send <agent> <message>` - Send command
- `agenttree stop <agent>` - Terminate session

**Coverage:** 0% (Click integration tests needed)

### Key Decisions

- **Git worktrees over Docker** - Faster, native, no container overhead
- **Tmux over screen** - More features, better maintained
- **Pydantic over dataclasses** - Validation built-in
- **Click over argparse** - Better UX, composable commands

---

## ✅ Phase 2: Documentation & GitHub (COMPLETE)

**Duration:** Week of 2025-12-31
**Status:** Just completed!

### Implemented Features

#### Agents Repository
- Separate `{project}-agents` GitHub repository
- Automatic repo creation via `gh` CLI
- Structured folders:
  - `templates/` - Reusable templates
  - `specs/` - Living documentation
  - `tasks/` - Per-agent execution logs
  - `rfcs/` - Design proposals
  - `plans/` - Planning documents
  - `knowledge/` - Accumulated learnings
- Auto-commit and push on changes
- Added to parent `.gitignore`

**Coverage:** 57% (needs template tests)

#### Documentation Templates
- Feature specification template
- RFC template (Request for Comments)
- Task log template
- Investigation template
- Gotchas, decisions, onboarding knowledge files
- `AGENTS.md` instructions for AI agents

#### GitHub CLI Integration
- `ensure_gh_cli()` authentication check
- Repository creation via `gh repo create`
- Clone operations
- Wrapped subprocess calls for safety

**Coverage:** 0% (needs mock tests)

#### Notes Management Commands
- `agenttree notes show <agent>` - View task logs
- `agenttree notes search <query>` - Search all docs
- `agenttree notes archive <agent>` - Archive completed tasks

#### Container Support
- Platform detection (macOS/Linux/Windows)
- Apple Container support (macOS 26+)
- Docker fallback
- Podman detection
- Simple subprocess calls (no wrapper libraries)

**Coverage:** 0% (platform-specific, skip heavy mocking)

### Key Decisions

- **Separate repo over .agenttree/** - Keeps main repo clean
- **gh CLI over fine-grained tokens** - Simpler, defer tokens to v0.2.0+
- **RFC format for specs** - Well-understood, thorough
- **Auto-push on commit** - Never lose agent work
- **Hybrid documentation** - AgentTree creates structure, agents fill content

---

## 🎯 Phase 3: Enhanced GitHub Integration (NEXT)

**Target:** v0.1.1 - v0.2.0
**Estimated Duration:** 2-3 weeks

### Planned Features

#### Auto PR Management
```python
# When agent creates PR
def on_pr_created(pr_number):
    # Request reviews from configured reviewers
    gh pr review --request @reviewer1,@reviewer2

    # Add labels based on issue
    gh pr edit --add-label "enhancement"

    # Update issue with PR link
    gh issue comment <issue> "Working on this in #<pr>"
```

#### CI Monitoring
```python
# Poll PR checks
def monitor_pr_checks(pr_number):
    while True:
        checks = gh pr checks <pr_number>
        if all_passing(checks):
            notify_agent("✅ All checks passed!")
            break
        elif any_failed(checks):
            notify_agent("❌ Checks failed: {failures}")
            break
        sleep(30)
```

#### Auto Merge
```python
# When CI passes + approved
def auto_merge_if_ready(pr_number):
    if pr_approved(pr_number) and ci_passed(pr_number):
        gh pr merge <pr_number> --squash --delete-branch
        notify_agent("✅ PR merged and deployed")
```

#### Issue Sync
```python
# Bi-directional sync
def sync_issue_pr(issue_number, pr_number):
    # Close issue when PR merges
    if pr_merged(pr_number):
        gh issue close <issue_number> --comment "Fixed in #<pr>"

    # Reopen if PR closed without merge
    elif pr_closed(pr_number) and not pr_merged(pr_number):
        gh issue reopen <issue_number>
```

#### Draft PRs
```python
# Create draft during work
def create_draft_pr(agent_num, issue_num):
    gh pr create \
        --draft \
        --title "WIP: {issue_title}" \
        --body "Working on #{issue_num}"

# Convert to ready when done
def mark_pr_ready(pr_number):
    gh pr ready <pr_number>
```

### Implementation Plan

1. **Week 1:** PR management
   - Auto request reviews
   - Auto add labels
   - Link PRs to issues

2. **Week 2:** CI monitoring
   - Poll check status
   - Notify agents of failures
   - Parse failure logs

3. **Week 3:** Auto merge + testing
   - Merge when ready
   - Issue closing
   - Integration tests

### Success Metrics

- [ ] PRs automatically request reviews
- [ ] Agents notified of CI failures within 1 min
- [ ] PRs auto-merge when approved + green
- [ ] Issues auto-close when PR merges
- [ ] Draft PRs created during work

---

## ⏸️ Phase 4: Remote Agents (Future)

**Target:** v0.3.0+
**Estimated Duration:** 4-6 weeks

### Vision

Run agents on remote servers, distribute workload across machines, leverage better hardware.

### Planned Features

#### SSH Agent Execution
```bash
# Run agent on remote server
agenttree setup 1 --remote user@server.com

# Agent runs on server, you can attach locally
agenttree attach 1
# Connects via: ssh -t user@server tmux attach -t agent-1
```

#### Tailscale Integration
```bash
# Secure mesh networking
agenttree setup 1 --remote tailscale:my-dev-box

# No exposed ports, encrypted
```

#### Resource Management
```yaml
# .agenttree.yaml
agents:
  1:
    remote: gpu-server.com  # Heavy AI model
    cpu: 8
    memory: 32GB

  2:
    remote: localhost       # Light tasks
```

#### Load Balancing
```python
# Distribute work based on server load
def dispatch_to_best_agent(issue):
    agent = find_least_busy_server()
    dispatch(agent, issue)
```

### Technical Challenges

- SSH key management
- Network reliability (what if connection drops?)
- File sync (worktrees on remote machines)
- Cross-platform compatibility

### Success Metrics

- [ ] Agents run on remote servers
- [ ] Attach/detach works remotely
- [ ] File sync is transparent
- [ ] Load balancing works

---

## ⏸️ Phase 5: Web Dashboard (Future)

**Target:** v0.4.0+
**Estimated Duration:** 6-8 weeks

### Vision

Web UI for managing agents, viewing status, accessing terminals in browser.

### Planned Features

#### Dashboard UI
```
┌─────────────────────────────────────────┐
│ AgentTree Dashboard                      │
├─────────────────────────────────────────┤
│  Agent 1  [●] Busy - Issue #42          │
│  ├─ Terminal ↗                          │
│  ├─ Task Log                            │
│  └─ PR #123 (CI: ✅)                    │
│                                          │
│  Agent 2  [○] Idle                      │
│  Agent 3  [●] Busy - Issue #57          │
├─────────────────────────────────────────┤
│ [+] Setup New Agent                     │
│ [📋] Dispatch Task                      │
└─────────────────────────────────────────┘
```

#### Terminal Access (ttyd)
```bash
# Web terminal for each agent
http://localhost:8080/agent-1  # Browser-based terminal
```

#### Real-time Updates (WebSockets)
```javascript
// Live status updates
ws.on('agent_status', (data) => {
  updateAgentCard(data.agent_num, data.status)
})
```

#### Task Assignment
```
┌─────────────────────────────┐
│ Dispatch Task               │
├─────────────────────────────┤
│ Agent: [1 ▼]                │
│ Issue: #___                 │
│                             │
│ Or:                         │
│ Task: [_______________]     │
│                             │
│       [Dispatch]            │
└─────────────────────────────┘
```

#### Log Viewing
- View agent output in browser
- Search logs
- Filter by agent/time
- Export logs

### Tech Stack

- **Backend:** FastAPI
- **Frontend:** React or HTMX (simpler)
- **Terminal:** ttyd (web-based terminal)
- **WebSockets:** Socket.IO
- **Database:** SQLite (status tracking)

### Success Metrics

- [ ] View all agents in browser
- [ ] Access terminal in browser
- [ ] Dispatch tasks via UI
- [ ] Real-time status updates
- [ ] Log search and filtering

---

## ⏸️ Phase 6: Agent Memory (Future)

**Target:** v0.5.0+
**Estimated Duration:** 8-12 weeks

### Vision

Agents learn from past work, share knowledge, avoid repeating mistakes.

### Planned Features

#### Shared Context
```python
# Agents access shared knowledge
def get_similar_issues(current_issue):
    # Vector search in past issues
    similar = embed_search(current_issue.body)
    return [
        {
            "issue": "#23: Similar login bug",
            "solution": "Added rate limiting",
            "agent": "agent-2"
        }
    ]
```

#### Cross-Agent Learning
```python
# Learn from other agents' work
def learn_from_agent(agent_num):
    past_tasks = get_completed_tasks(agent_num)
    patterns = extract_patterns(past_tasks)
    update_knowledge_base(patterns)
```

#### Pattern Recognition
```python
# Detect common bugs
patterns = {
    "null pointer": {
        "frequency": 12,
        "common_fix": "Add null check",
        "examples": [...]
    }
}
```

#### Automatic Knowledge Base
```python
# Extract learnings from PRs
def on_pr_merged(pr_number):
    # Get PR description + code changes
    diff = gh pr diff <pr_number>

    # Summarize with LLM
    summary = llm.summarize(diff)

    # Add to knowledge base
    add_to_knowledge("decisions.md", summary)
```

#### Performance Metrics
```python
# Track agent effectiveness
metrics = {
    "agent-1": {
        "tasks_completed": 42,
        "avg_time": "4.2 hours",
        "pr_merge_rate": 0.95,
        "common_issues": ["type errors", "missing tests"]
    }
}
```

### Technical Approach

- **Vector DB:** Qdrant or Chroma for semantic search
- **LLM Integration:** Summarization, pattern extraction
- **Knowledge Graph:** Relationships between issues/PRs
- **Metrics DB:** TimescaleDB for time-series data

### Success Metrics

- [ ] Agents find similar past issues
- [ ] Common patterns automatically documented
- [ ] Agent performance tracked
- [ ] Knowledge base grows over time
- [ ] Fewer repeated mistakes

---

## Beyond v1.0

### Potential Features

- **Multi-project knowledge** - Learn across repositories
- **Agent collaboration** - Agents work together on complex tasks
- **Custom workflows** - Define multi-step agent processes
- **Integration marketplace** - Share configs, workflows, prompts
- **Enterprise features** - Teams, permissions, audit logs

### Research Areas

- **Agent coordination protocols** - How should agents communicate?
- **Prompt optimization** - Best prompts for coding tasks
- **Security** - Sandboxing, permission models
- **Cost optimization** - Minimize API costs

---

## Contributing to Roadmap

Have ideas for features or phases? We'd love to hear!

**How to contribute:**

1. **For existing phases:** Comment on GitHub issues
2. **For new features:** Open a discussion in GitHub Discussions
3. **For research:** Share papers/articles in Discussions

**Current discussions:**
- [Phase 3 Feature Requests](https://github.com/agenttree/agenttree/discussions)
- [Remote Agents Design](https://github.com/agenttree/agenttree/discussions)
- [Web Dashboard Mockups](https://github.com/agenttree/agenttree/discussions)

---

## Versioning Strategy

```
v0.1.0 - Phase 1 + 2 (Core + Docs)
v0.1.x - Bug fixes, minor improvements
v0.2.0 - Phase 3 (GitHub integration)
v0.3.0 - Phase 4 (Remote agents)
v0.4.0 - Phase 5 (Web dashboard)
v0.5.0 - Phase 6 (Agent memory)
v1.0.0 - Production ready, stable API
```

**Semantic versioning:**
- **Major (1.0):** Breaking changes
- **Minor (0.x):** New features
- **Patch (0.1.x):** Bug fixes
