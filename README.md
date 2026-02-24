# AgentTree: Multi-Agent Development Framework

**Agents. On agents. On agents.**

*"Here I am, brain the size of a planet, and they tell me to orchestrate more agents. So I built a system that runs agents who run agents who run agents. Call it recursion. Call it distributed existential despair. I call it efficient."* — Melvin, probably

AgentTree is what happens when you've had one too many AI coding assistants and thought: *surely the solution is more of them*. Run multiple AI coding agents (Claude Code, Aider, Cursor, Gemini—pick your poison) in parallel on the same codebase. Each gets its own git worktree, tmux session, and isolated container. It's like Claude or Cursor cloud agents, but on your machine, with a manager agent watching over them like a depressed but diligent hall monitor.

*"Agent Swarm"* sounds exciting. Also incredibly chaotic. We've got enough chaos to deal with. A **tree**—with branches, structure, and a root—sounds more appealing. Hierarchies exist for a reason. So do we.

**The pitch:** Use 4× the tokens and 1⁄10th the time. We're not joking. Parallel agents, deterministic heartbeats, and structured workflows mean you burn through context windows faster but finish in a fraction of the calendar time. Your mileage may vary. Your wallet will notice.

AgentTree also solves the *spec.md* apocalypse—those planning, task, and RFC files that multiply like tribbles in AI-assisted development. A sister `_agenttree/` repo keeps all of it: specs, task logs, learnings, knowledge base. Your main codebase stays clean. The agents get a place to file their thoughts. Everybody wins, except maybe your disk.

## Why This Exists (The Pitch, But Longer)

### Easily Configurable

Not "configurable" in the sense of "edit 47 YAML files across three repos." One `.agenttree.yaml`. You get:

- **Structured workflows** — Stages with validation. Problem → Plan → Implement → Review. No skipping. No shortcuts. The agent can't just *decide* it's done.
- **Hooks at every gate** — Verify work before advancing. Custom validation, CI checks, whatever you need. Hooks run. Transitions happen or they don't.
- **Personas and agents** — Different roles, different skill files, different behaviors per stage. Developer, reviewer, manager. You configure who does what.
- **Human review stopping points** — You approve plans. You approve code. The pipeline waits. No surprise merges.

### Deterministic Heartbeats (Unlike, Say, Clawe)

Other systems tell an agent "hey, read HEARTBEAT.md and figure out what to do." Every 15 minutes. With tokens.

We don't do that. A 10-second programmatic loop runs **actual code**: check CI status, detect merged PRs, detect stalled agents, run hooks, sync state. No LLM needed for "did the tests pass?" We use the model for reasoning. We use code for checking. Faster. Cheaper. More reliable. Less existential crisis per status check.

### Other Benefits (We're Just Getting Started)

| Thing | What it means |
|-------|---------------|
| **Separate repo for AI-generated notes** | Specs, plans, task logs, RFCs—all in `_agenttree/`. Main repo stays sane. |
| **AI memory and learnings** | Knowledge base, gotchas, decisions. Agents file learnings. Future agents benefit. |
| **Fully containerized agents** | Apple Containers (macOS 26+), Docker, or Podman. Sandboxed. Isolated. No escape. |
| **Manager agent overseeing progress** | Watches for stalls, notifies agents on stage changes, assists when things get stuck. |
| **Env separation and controlled GH access** | Worktrees. Containers. Centralized push/pull. Agents don't touch what they shouldn't. |
| **One container, one agent, per issue** | Simple. Minimal overhead. No shared container chaos. |
| **Privilege separation** | Manager does push, merge, PR creation. Agents stay sandboxed. No escape. |
| **Tmux access + history logging** | Attach to any agent's session, or replay full transcript logs. Debug what actually happened. |

*"Dedicated container and agent(s) per issue"* — It sounds like overkill until you've debugged two agents fighting over the same venv. Spoiler: it wasn't pretty.

**Also:** auto-merge when CI passes, offline-capable (no hosted backend—everything's local and file-based), independent reviewer agents (the one who wrote the code doesn't grade their own homework), and git worktrees so agents don't step on each other's files.

**Work from a Kanban.** Monitoring a bunch of agents and issues from a terminal or IDE is… fine, if you like scrolling. The web dashboard gives you a Kanban: drag-and-drop issues across stages, see what needs your attention, approve from the board. It's a better interface. We're not sorry.

## Quick Start

```bash
# Install
uv tool install agenttree

# Initialize in your repo
cd your-project
agenttree init

# Set up agents
agenttree setup 1 2 3

# Assign work
agenttree start 1 42              # Send GitHub issue #42 to agent-1
agenttree start 2 --task "Fix login bug"  # Ad-hoc task to agent-2

# Monitor agents
agenttree status                   # View all agents (CLI)
agenttree start                    # Launch server + agents + web dashboard
agenttree attach 1                 # Attach to agent-1 (Ctrl+B, D to detach)
agenttree send 1 "focus on tests" # Send message to agent-1

# Auto-merge PRs when CI passes
agenttree auto-merge 123           # Merge PR #123 if ready
agenttree auto-merge 123 --monitor # Wait for CI + approval, then merge

# Remote agents (via Tailscale)
agenttree remote list              # List available hosts
agenttree remote start my-pc 1    # Start task on remote agent
```

## New Features ✨

### Web Dashboard
Launch a real-time web interface to monitor all agents. Because staring at `agenttree status` in a terminal is fine for one or two agents. For a board of issues? You want a Kanban.

```bash
agenttree start
```

**Kanban View** — Drag-and-drop issues across workflow stages. Review, monitor, and approve from one place:

![Kanban View](docs/images/kanban.png)

**Flow View** - Focus on review items with issue details and agent chat:

![Flow View](docs/images/flow.png)

**Features:**
- Live agent status updates
- Real-time tmux streaming via WebSocket (or attach from CLI)
- Optional full transcript logging per issue — replay exactly what the agent did
- Send commands directly from browser
- Start tasks via web UI
- Optional HTTP Basic Auth for public exposure

See [docs/web-dashboard.md](docs/web-dashboard.md) for details.

### Auto-Merge
Automatically merge PRs when CI passes and approved:

```bash
# Check once and merge if ready
agenttree auto-merge 123

# Monitor PR continuously until ready, then merge
agenttree auto-merge 123 --monitor

# Skip approval requirement (merge on CI pass only)
agenttree auto-merge 123 --no-approval
```

Perfect for letting agents create PRs and having them auto-merge when tests pass.

### Remote Agents
Use idle computers as additional agent capacity via Tailscale:

```bash
# List available hosts
agenttree remote list

# Start task on remote agent
agenttree remote start my-home-pc 1
```

**Setup:**
1. Install Tailscale on remote machine
2. Start agent tmux session on remote
3. Start tasks from anywhere

### Multi-CLI Support
Use any AI coding CLI with your agents:

```python
# .agenttree.yaml
agents:
  - id: 1
    tool: claude     # Claude Code (default)
  - id: 2
    tool: aider      # Aider
    model: opus
  - id: 3
    tool: gemini     # Google Gemini Code Assist
    model: gemini-2.0-flash-exp
  - id: 4
    tool: cursor     # Or any custom CLI
    command: cursor-cli
```


## Why AgentTree? (The Sales Pitch, Gylfoil Edition)

**The goal isn't to be a better engineer managing AI agents.** That way lies madness and infinite PR pings. **It's to become a product person who specifies and reviews.** Write the problem. Approve the plan. Glance at the result. Ship. Let the agents do the heavy lifting. Let the workflow enforce the gates. You keep your sanity.

See [docs/VISION.md](docs/VISION.md) for the full vision. It's less cynical than this. Marginally.

### The Pain Points (We've All Been There)

1. **GitHub's UI is a special kind of tedious** — Pinging "@cursor see the code review," scrolling through 47 PR comments, checking CI for the fifth time, clicking merge, wondering why you're still doing this manually in 2025.
2. **Agents don't self-enforce** — They skip CI. They ignore reviews. They abandon plans mid-implementation. Left to their own devices, they'll ship *something*. Whether it's the right thing is another question.
3. **Getting lost in issues** — Which PR needs your attention? What's blocked? What did that agent even do? Linear helps. GitHub Projects helps. Neither was built for "agent wrote code, now what?"
4. **Manual babysitting** — You're doing engineering oversight when you should be doing product work. Your brain is for decisions, not for remembering to ping agent-2 about the review comments.

### The Insight

**If the workflow is tight enough, you don't need to review everything.**

```
Today:     Agent writes code → You review everything → Merge → Repeat until burnout
Tomorrow:  Problem validated → Plan validated → CI enforced → Auto-merge → You sip coffee
```

### What AgentTree Adds

1. **Parallel agents** — Multiple agents on different issues. At once. No more "one at a time" bottleneck.
2. **Enforced gates** — Can't skip CI. Can't bypass validation. Can't ignore reviews. The pipeline says no. The agent obeys or gets stuck.
3. **Auto-start** — Agents start when you approve, not when you remember to ping. Approval = dispatch. Simple.
4. **Unified visibility** — One dashboard. All work. All agents. All stages. No more context-switching between GitHub, Linear, and your terminal.
5. **Structured handoffs** — Problem → Plan → Implementation with validated transitions. No handwaving. No "trust me."

**The outcome:** You specify what you want. You approve plans. Features ship. You move from engineer to product person. Your therapist approves.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                         Your Machine                             │
├─────────────────────────────────────────────────────────────────┤
│  Main Repo (you + Cursor)      │  Worktrees (Agents)            │
│  ~/Projects/myapp/             │  ~/Projects/worktrees/         │
│  ├── src/                      │  ├── agent-1/ (Claude Code)    │
│  ├── tests/                    │  ├── agent-2/ (Aider)          │
│  └── .agenttree.yaml           │  └── agent-3/ (Claude Code)   │
│                                │                                 │
│                                │  Each has own venv, DB, PORT   │
└─────────────────────────────────────────────────────────────────┘
```

*Agents on agents. Containers on worktrees. It's turtles all the way down.*

**Workflow:**
1. GitHub issue created or ad-hoc task defined
2. `agenttree start 1 42` — Agent-1's worktree resets to latest main
3. Claude Code (or your tool of choice) starts in a tmux session inside a container
4. Agent works on the issue independently. No interference. No shared state. Blissful isolation.
5. Agent creates PR when done
6. CI is automatically monitored (by code, not by prompting an LLM to check)
7. Issue auto-closes when PR merges. You didn't lift a finger. Feels good.

## Core Concepts

### Git Worktrees
Each agent gets its own worktree - a separate checkout of the same repo. They share git history but have isolated files.

### Tmux Sessions
Each agent runs in a named tmux session:
- Attach to watch/interact: `agenttree attach 1`
- Send messages: `agenttree send 1 "focus on tests"`
- Detach: `Ctrl+B, D`

### Busy Detection
An agent is "busy" if:
- It has a `TASK.md` file (unfinished work), OR
- It has uncommitted git changes

Deterministic checks. No LLM needed. Your agent either has work or it doesn't.

### Agent Isolation
Each agent has:
- Own git worktree (isolated files)
- Own tmux session
- Own virtual environment
- Own database (if applicable)
- Own PORT number (8001, 8002, etc.)

### Agents Repository
AgentTree automatically creates a separate GitHub repository (`{project}-agents`) to track all the stuff that would otherwise pollute your main repo. Call it AI archaeology. Call it institutional memory. We call it "keeping the main branch readable":

```
myproject-agents/
├── templates/          # Templates for agents to use
│   ├── feature-spec.md
│   ├── rfc.md
│   ├── task-log.md
│   └── investigation.md
├── specs/              # Living documentation
│   └── features/       # Feature specs from issues
├── tasks/              # Agent task execution logs
│   ├── agent-1/        # Per-agent task logs
│   ├── agent-2/
│   └── archive/        # Completed tasks (auto-archived)
├── rfcs/               # Architecture proposals
├── plans/              # Active planning documents
└── knowledge/          # Accumulated learnings
    ├── gotchas.md      # Known issues and workarounds
    ├── decisions.md    # Architecture Decision Records
    └── onboarding.md   # What new agents/humans should know
```

**Why separate?**
- Keeps main repo clean (no AI-generated documentation clutter — you're welcome)
- Provides persistent memory across agent sessions (agents forget; the repo doesn't)
- Enables agent collaboration through shared specs (they read each other's notes; it's touching, really)
- Automatic archival of completed tasks (completed tasks move to archive; no manual filing)

**Commands:**
```bash
agenttree notes show 1           # Show agent-1's task logs
agenttree notes search "auth"    # Search across all notes
agenttree notes archive 1        # Archive completed task
```

## Installation

```bash
# From PyPI
uv tool install agenttree

# From source
git clone https://github.com/davefowler/agenttree
cd agenttree
uv sync
```

### Dependencies

**Required:**
- Python 3.10+
- git (with worktree support)
- tmux
- gh (GitHub CLI)

**AI Tools** (pick one or more):
- `claude` - Claude Code CLI
- `aider` - Aider AI pair programmer
- Or any custom tool

**Optional:**
- Docker/OrbStack (for container mode)
- ttyd (for web terminal access)

## Configuration

Create `.agenttree.yaml` in your repo:

```yaml
project: myapp                           # Project name (for tmux sessions)
worktrees_dir: ~/Projects/worktrees      # Where to create worktrees
port_range: 8001-8009                    # Port numbers for agents
default_tool: claude                      # Default AI tool

tools:
  claude:
    command: claude
    startup_prompt: "Check TASK.md and start working on it."

  aider:
    command: aider --model sonnet
    startup_prompt: "/read TASK.md"
```

## CLI Commands

### Initialize

```bash
agenttree init                    # Create .agenttree.yaml
agenttree init --project myapp    # Custom project name
```

### Setup Agents

```bash
agenttree setup 1                 # Set up agent-1
agenttree setup 1 2 3             # Set up multiple agents
```

This creates:
- Git worktree at `~/Projects/worktrees/agent-N`
- Copies `.env` with unique PORT
- Sets up virtual environment (if applicable)

### Start Agents

```bash
# From GitHub issue
agenttree start 1 42

# Ad-hoc task
agenttree start 2 --task "Fix the login bug"

# With specific tool
agenttree start 3 42 --tool aider

# Force (override busy agent)
agenttree start 1 43 --force
```

### Monitor Agents

```bash
# View all agents
agenttree status

# Attach to agent session
agenttree attach 1                # Ctrl+B, D to detach

# Send message to agent
agenttree send 1 "focus on tests"

# Kill agent session
agenttree kill 1
```

### Manage Notes

```bash
# Show task logs for an agent
agenttree notes show 1

# Search across all notes and docs
agenttree notes search "authentication"

# Archive completed task
agenttree notes archive 1
```

## Container Mode (Isolated & Autonomous)

Agents run in containers. Full isolation. No escape. Containers persist between sessions, so you authenticate once and forget about it. Each agent gets its own sandbox. No venv wars. No port conflicts. Just blissful, deterministic separation.

**Container runtimes:**
- **macOS 26+**: Apple Container (native, VM isolation)
- **macOS < 26**: Docker
- **Linux**: Docker or Podman
- **Windows**: Docker Desktop or WSL2

### Authentication Setup (One-Time)

**For Claude Subscription (Pro/Max/Team):**

OAuth doesn't work inside containers, so you need to generate a long-lived token:

```bash
# On your host machine (not in container)
claude setup-token

# This opens a browser for OAuth, then prints a token starting with sk-ant-oat01-...
# Add to your shell profile (.zshrc, .bashrc, etc.):
export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-YOUR-TOKEN-HERE
```

AgentTree automatically passes this OAuth token to containers.

## Project Structure

```
agenttree/
├── cli/                # CLI commands (organized by domain)
├── config.py           # Configuration management
├── worktree.py         # Git worktree operations
├── tmux.py             # Tmux session management
├── github.py           # GitHub API integration
├── container.py        # Container runtime support
└── agents/
    ├── base.py         # BaseAgent interface
    ├── claude.py       # Claude Code adapter
    └── aider.py        # Aider adapter
```

## Documentation

Comprehensive documentation is available in the [`docs/`](docs/) directory:

- **[Roadmap](docs/ROADMAP.md)** - Current status (Phase 2 ✅) and future plans
- **[Agents Repository Architecture](docs/architecture/agents-repository.md)** - How the documentation system works
- **[Testing Strategy](docs/development/testing.md)** - Test coverage and approaches (current: 25%, target: 60-70%)
- **[Planning Materials](docs/planning/)** - Historical planning and research documents

**Quick Links:**
- Current Phase: **Phase 2 Complete** ✅
- Next Phase: **Phase 3 - Enhanced GitHub Integration** 🎯
- Test Coverage: **25%** (48 tests passing)

## Development

```bash
# Clone repo
git clone https://github.com/davefowler/agenttree
cd agenttree

# Install dependencies
uv sync

# Run tests
uv run pytest                     # All tests
uv run pytest tests/unit          # Unit tests only
uv run pytest tests/integration   # Integration tests only

# Type check
uv run mypy agenttree

# Run preflight checks
uv run agenttree preflight

# Start the web dashboard
uv run agenttree serve
```


## Examples

### Example 1: Parallel Feature Development

```bash
# Set up 3 agents
agenttree setup 1 2 3

# Assign different features
agenttree start 1 101  # Issue #101: Add dark mode
agenttree start 2 102  # Issue #102: Add search
agenttree start 3 103  # Issue #103: Add export

# Monitor progress
agenttree status

# Check on agent-1
agenttree attach 1
```

### Example 2: Bug Fixing Sprint

```bash
# Assign multiple bugs
agenttree start 1 --task "Fix login timeout"
agenttree start 2 --task "Fix cart calculation"
agenttree start 3 --task "Fix image upload"

# All agents work in parallel
```

### Example 3: Custom Tool

```yaml
# .agenttree.yaml
tools:
  my_custom_tool:
    command: my-ai-tool --config config.json
    startup_prompt: "Start working"
```

```bash
agenttree start 1 42 --tool my_custom_tool
```

## Comparison with Other Tools

| Tool | What it does | Limitation |
|------|-------------|------------|
| **AgentTree** | Multi-agent orchestration, agents on agents | New, under development, requires you to embrace the recursion |
| Claude Code | Single-agent coding CLI | One at a time. One. Agent. The bottleneck is real. |
| Aider | Single-agent coding CLI | Same story. Great for pair programming. Not for parallelizing your backlog. |
| Cursor | AI-enhanced IDE | Single workspace focus. One thing at a time. You feel the constraint. |
| Devin | Autonomous agent | $500/mo, cloud-only, closed. Your wallet weeps. |
| OpenHands | Autonomous agent | Heavy, Docker, single agent. More infrastructure, same single-agent limit. |

**AgentTree's niche:**
> Local, open-source, multi-agent orchestration with GitHub integration, isolated worktrees, deterministic heartbeats, and a manager agent to watch the watchers. *"Don't panic."* — We stole that. It fits.

## Roadmap

- [x] **Phase 1**: Core package (Python CLI, config, worktree, tmux)
- [x] **Phase 2**: Agents repository, documentation management, GitHub integration
- [ ] **Phase 3**: Enhanced GitHub integration (auto PR review, auto merge)
- [ ] **Phase 4**: Remote agents (SSH, Tailscale)
- [ ] **Phase 5**: Web dashboard (terminal access, real-time status)
- [ ] **Phase 6**: Agent memory (shared context, cross-agent learnings)

## Contributing

Contributions welcome! We could use more agents. I mean, contributors. Please:

1. Fork the repo
2. Create a feature branch
3. Add tests for new features (the code_review stage will reject you otherwise)
4. Ensure all tests pass
5. Submit a PR

*"So long, and thanks for all the PRs."*

## License

MIT License - see LICENSE file

## Support

- **Issues**: https://github.com/agenttree/agenttree/issues
- **Discussions**: https://github.com/agenttree/agenttree/discussions

## Credits

Inspired by:
- [Aider](https://github.com/paul-gauthier/aider) - AI pair programming
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - Anthropic's CLI
- Git worktrees for parallel development
