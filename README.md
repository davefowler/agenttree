# AgentTree: Multi-Agent Development Framework

**Orchestrate multiple AI coding agents across git worktrees**

AgentTree lets you run multiple AI coding agents (Claude Code, Aider, etc.) in parallel on the same codebase.  It's like claude or cursor cloud code agents but on your machine with a lot more capabilities.  Each agent gets its own git worktree, tmux session, and isolated environment.

AgentTree also attempts to organize the many planning, task and spec.md files that accumulate naturally in AI assisted development.  To remove this noise (and the noise of the agents assigning/sharing tasks to each other) it creates an /agents folder with a sister git repo that organizes these files and all their commits in your working directory but out of your main code base.

## Quick Start

```bash
# Install
pip install agenttree

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
agenttree web                      # Launch web dashboard at http://127.0.0.1:8080
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
Launch a real-time web interface to monitor all agents:

```bash
agenttree web
# Open http://127.0.0.1:8080
```

**Kanban View** - Drag-and-drop issues across workflow stages:

![Kanban View](docs/images/kanban.png)

**Flow View** - Focus on review items with issue details and agent chat:

![Flow View](docs/images/flow.png)

**Features:**
- Live agent status updates
- Real-time tmux streaming via WebSocket
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


## Why AgentTree?

**The goal isn't to be a better engineer managing AI agents. It's to become a product person who specifies and reviews.**

See [docs/VISION.md](docs/VISION.md) for the full vision.

### The Pain Points

1. **GitHub's UI is tedious** - Constantly pinging "@cursor see the code review", scrolling through PRs, checking CI status, clicking merge
2. **Agents don't self-enforce** - They skip CI, ignore reviews, don't follow plans unless forced
3. **Getting lost in issues** - No clear view of "what needs my attention NOW"
4. **Manual babysitting** - You're doing engineering oversight when you should be doing product work

### The Insight

**If the workflow is tight enough, you don't need to review.**

```
Today:     Agent writes code → You review everything → Merge
Tomorrow:  Problem validated → Plan validated → CI enforced → Auto-merge
```

### What AgentTree Adds

1. **Parallel agents** - Multiple agents on different issues simultaneously
2. **Enforced gates** - Can't skip CI, can't bypass validation, can't ignore reviews
3. **Auto-start** - Agents start when you approve, not when you remember to ping
4. **Unified visibility** - One dashboard for all work across all agents
5. **Structured handoffs** - Problem → Plan → Implementation with validated transitions

**The outcome:** You specify what you want. You approve plans. Features ship. You move from engineer to product person.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                         Your Machine                             │
├─────────────────────────────────────────────────────────────────┤
│  Main Repo (you + Cursor)      │  Worktrees (Agents)            │
│  ~/Projects/myapp/             │  ~/Projects/worktrees/         │
│  ├── src/                      │  ├── agent-1/ (Claude Code)    │
│  ├── tests/                    │  ├── agent-2/ (Aider)          │
│  └── .agenttree.yaml           │  └── agent-3/ (Claude Code)    │
│                                │                                 │
│                                │  Each has own venv, DB, PORT   │
└─────────────────────────────────────────────────────────────────┘
```

**Workflow:**
1. GitHub issue created or ad-hoc task defined
2. `agenttree start 1 42` - Agent-1's worktree resets to latest main
3. Claude Code starts in a tmux session
4. Agent works on the issue independently
5. Agent creates PR when done
6. CI is automatically monitored
7. Issue auto-closes when PR merges

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

### Agent Isolation
Each agent has:
- Own git worktree (isolated files)
- Own tmux session
- Own virtual environment
- Own database (if applicable)
- Own PORT number (8001, 8002, etc.)

### Agents Repository
AgentTree automatically creates a separate GitHub repository (`{project}-agents`) to track:

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
- Keeps main repo clean (no AI-generated documentation clutter)
- Provides persistent memory across agent sessions
- Enables agent collaboration through shared specs
- Automatic archival of completed tasks

**Commands:**
```bash
agenttree notes show 1           # Show agent-1's task logs
agenttree notes search "auth"    # Search across all notes
agenttree notes archive 1        # Archive completed task
```

## Installation

```bash
# From PyPI
pip install agenttree

# From source
git clone https://github.com/agenttree/agenttree
cd agenttree
pip install -e ".[dev]"
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

Agents run in containers for isolation and security. Containers persist between sessions so you only need to authenticate once.

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
git clone https://github.com/agenttree/agenttree
cd agenttree

# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=agenttree

# Format code
black agenttree tests

# Type check
mypy agenttree

# Lint
ruff agenttree
```

**For beta testing AgentTree with your projects:**
```bash
# Install in development mode (live updates)
cd ~/my-project
python -m venv venv
source venv/bin/activate
pip install -e /path/to/agenttree

# Now any changes to AgentTree code immediately affect this project
```

See [Testing Strategy](docs/development/testing.md) for more details.

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
| **AgentTree** | Multi-agent orchestration | New, under development |
| Claude Code | Single-agent coding CLI | One at a time, single agent |
| Aider | Single-agent coding CLI | One at a time, single agent |
| Cursor | AI-enhanced IDE | Single workspace focus |
| Devin | Autonomous agent | $500/mo, cloud-only, closed |
| OpenHands | Autonomous agent | Heavy, Docker, single agent |

**AgentTree's niche:**
> Local, open-source, multi-agent orchestration with GitHub integration and isolated worktrees.

## Roadmap

- [x] **Phase 1**: Core package (Python CLI, config, worktree, tmux)
- [x] **Phase 2**: Agents repository, documentation management, GitHub integration
- [ ] **Phase 3**: Enhanced GitHub integration (auto PR review, auto merge)
- [ ] **Phase 4**: Remote agents (SSH, Tailscale)
- [ ] **Phase 5**: Web dashboard (terminal access, real-time status)
- [ ] **Phase 6**: Agent memory (shared context, cross-agent learnings)

## Contributing

Contributions welcome! Please:

1. Fork the repo
2. Create a feature branch
3. Add tests for new features
4. Ensure all tests pass
5. Submit a PR

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
