# AgentTree: Multi-Agent Development Framework

**Orchestrate multiple AI coding agents across git worktrees**

AgentTree lets you run multiple AI coding agents (Claude Code, Aider, etc.) in parallel on the same codebase. Each agent gets its own git worktree, tmux session, and isolated environment.

## Quick Start

```bash
# Install
pip install agenttree

# Initialize in your repo
cd your-project
agenttree init

# Set up agents
agenttree setup 1 2 3

# Dispatch work
agenttree dispatch 1 42           # Send GitHub issue #42 to agent-1
agenttree dispatch 2 --task "Fix login bug"  # Ad-hoc task to agent-2

# Monitor
agenttree status                   # View all agents
agenttree attach 1                 # Attach to agent-1 (Ctrl+B, D to detach)
agenttree send 1 "focus on tests" # Send message to agent-1
```

## Why AgentTree?

**Problems it solves:**

1. **Single-threaded development** - Work on multiple issues simultaneously
2. **Context switching** - Each agent maintains its own context
3. **Agent interference** - Isolated worktrees prevent conflicts
4. **CI blind spots** - Automatically monitor PR checks
5. **Lost knowledge** - Task history preserved in git
6. **No orchestration** - Programmatic task dispatch

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
2. `agenttree dispatch 1 42` - Agent-1's worktree resets to latest main
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

### Dispatch Tasks

```bash
# From GitHub issue
agenttree dispatch 1 42

# Ad-hoc task
agenttree dispatch 2 --task "Fix the login bug"

# With specific tool
agenttree dispatch 3 42 --tool aider

# Force (override busy agent)
agenttree dispatch 1 43 --force
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

For autonomous operation with safety:

```bash
# Run in container (isolated from host)
agenttree dispatch 1 42 --container

# Dangerous mode (skip permissions, requires container)
agenttree dispatch 1 42 --container --dangerous
```

**Container runtimes:**
- **macOS 26+**: Apple Container (native, VM isolation)
- **macOS < 26**: Docker
- **Linux**: Docker or Podman
- **Windows**: Docker Desktop or WSL2

## Project Structure

```
agenttree/
├── cli.py              # CLI commands
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

## Examples

### Example 1: Parallel Feature Development

```bash
# Set up 3 agents
agenttree setup 1 2 3

# Dispatch different features
agenttree dispatch 1 101  # Issue #101: Add dark mode
agenttree dispatch 2 102  # Issue #102: Add search
agenttree dispatch 3 103  # Issue #103: Add export

# Monitor progress
agenttree status

# Check on agent-1
agenttree attach 1
```

### Example 2: Bug Fixing Sprint

```bash
# Dispatch multiple bugs
agenttree dispatch 1 --task "Fix login timeout"
agenttree dispatch 2 --task "Fix cart calculation"
agenttree dispatch 3 --task "Fix image upload"

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
agenttree dispatch 1 42 --tool my_custom_tool
```

## Comparison with Other Tools

| Tool | What it does | Limitation |
|------|-------------|------------|
| **AgentTree** | Multi-agent orchestration | New, under development |
| Claude Code | Single-agent coding CLI | One at a time, no dispatch |
| Aider | Single-agent coding CLI | One at a time, no dispatch |
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
