# AgentTree

Run multiple AI coding agents in parallel on the same codebase. Each agent gets its own git worktree, tmux session, and optional container — fully isolated, working on separate issues simultaneously.

AgentTree works with Claude Code, Aider, Gemini, Cursor, or any CLI-based coding tool. You assign issues, agents do the work, a structured workflow enforces quality gates, and PRs get merged when CI passes.

![Kanban View](docs/images/kanban.png)

## Why AgentTree

**Parallel by default.** Instead of working issues one at a time, run 3-5 agents on different issues at once. Each gets its own worktree so there are no file conflicts, no shared state, no coordination overhead.

**Structured workflow with gates.** Every issue moves through stages — explore, plan, implement, review — with validation hooks at each transition. Tests must pass. Specs must have required sections. Plans get human approval before implementation starts. Agents can't skip steps or self-approve.

**Deterministic monitoring.** A programmatic heartbeat loop checks CI status, detects stalled agents, runs hooks, and syncs state every 10 seconds. No LLM tokens spent on status checks. Code checks what code can check; the model handles reasoning.

**Your codebase stays clean.** All agent-generated documents (specs, plans, reviews, task logs) live in a separate `_agenttree/` repository. Your main repo never gets cluttered with AI planning artifacts.

**Fully local.** No hosted backend. Everything runs on your machine (or remote machines via Tailscale). File-based state. Works offline.

## Quick Start

### Install

```bash
uv tool install agenttree
```

### Set up a project

```bash
cd your-project
agenttree init
```

This creates `.agenttree.yaml` in your repo with default configuration. Edit it to set your preferred AI tool, worktree directory, and workflow.

### Create agents and assign work

```bash
# Set up agent worktrees
agenttree setup 1 2 3

# Assign GitHub issues
agenttree start 1 42              # Agent 1 works on issue #42
agenttree start 2 55              # Agent 2 works on issue #55

# Or assign ad-hoc tasks
agenttree start 3 --task "Fix the login timeout bug"
```

### Monitor and interact

```bash
agenttree status                   # See all agents and their stages
agenttree attach 1                 # Attach to agent 1's tmux session (Ctrl+B, D to detach)
agenttree send 1 "focus on tests"  # Send a message to a running agent
agenttree output 1                 # View agent's terminal output
```

### Web dashboard

```bash
agenttree start                    # Launch server, agents, and web dashboard
```

The dashboard gives you a Kanban board of all issues across workflow stages. Drag and drop issues, monitor agent progress, send commands, and approve reviews — all from the browser.

![Flow View](docs/images/flow.png)

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                         Your Machine                            │
├─────────────────────────────────────────────────────────────────┤
│  Main Repo (you)                 │  Worktrees (Agents)          │
│  ~/projects/myapp/               │  ~/projects/worktrees/       │
│  ├── src/                        │  ├── agent-1/ (Claude Code)  │
│  ├── tests/                      │  ├── agent-2/ (Aider)        │
│  └── .agenttree.yaml             │  └── agent-3/ (Claude Code)  │
│                                  │                               │
│                                  │  Each has own venv, DB, port  │
└─────────────────────────────────────────────────────────────────┘
```

1. You create or assign an issue
2. `agenttree start 1 42` — Agent 1's worktree resets to latest main
3. The configured AI tool (Claude Code, Aider, etc.) starts in a tmux session
4. The agent moves through workflow stages: explore → plan → implement → review
5. Validation hooks enforce quality at each gate (tests pass, specs complete, etc.)
6. The agent creates a PR when implementation is done
7. CI is monitored programmatically — auto-merge when it passes

### Workflow stages

The default workflow enforces this progression:

| Stage | What happens |
|-------|-------------|
| **Explore** | Agent defines the problem and researches the codebase |
| **Plan** | Agent drafts a spec, self-assesses, revises, then you review |
| **Implement** | Agent writes code, runs self-review, passes independent review |
| **CI + Review** | PR is created, CI must pass, you give final approval |
| **Accepted** | PR is merged, agent resources are cleaned up |

Each stage has configurable hooks — run tests, check for required sections in documents, validate formatting, rebase branches. If a hook fails, the agent stays in the current stage until the issue is resolved.

You can also define a `quick` flow that skips research and planning for trivial changes (typo fixes, config updates).

## Configuration

All configuration lives in `.agenttree.yaml`:

```yaml
project: myapp
worktrees_dir: ~/projects/worktrees
port_range: 8001-8009
default_tool: claude

tools:
  claude:
    command: claude
    startup_prompt: "Check TASK.md and start working on it."
  aider:
    command: aider --model sonnet
    startup_prompt: "/read TASK.md"
```

### Multi-tool support

Use different AI tools for different agents:

```yaml
tools:
  claude:
    command: claude
  aider:
    command: aider
  gemini:
    command: gemini
  custom:
    command: my-ai-tool --config config.json
```

```bash
agenttree start 1 42 --tool claude
agenttree start 2 55 --tool aider
```

### Roles

Assign different roles for different workflow stages:

```yaml
roles:
  developer:
    tool: claude
    model: opus
    container:
      image: agenttree-agent:latest

  reviewer:
    tool: claude
    model: sonnet
    skill: independent_review.md
```

The developer writes the code. A separate reviewer agent does the independent review. The agent who wrote the code doesn't grade their own work.

## Container mode

Agents can run inside containers for full isolation:

- **macOS 26+**: Apple Containers (native VM isolation)
- **macOS < 26 / Linux / Windows**: Docker or Podman

Each agent gets its own container. No shared environments, no dependency conflicts, no port collisions.

### Authentication in containers

For Claude Code with a subscription (Pro/Max/Team):

```bash
# Generate a long-lived token on your host machine
claude setup-token

# Add to your shell profile
export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-YOUR-TOKEN-HERE
```

AgentTree passes this token to containers automatically.

## Remote agents

Use idle machines as additional agent capacity via Tailscale:

```bash
agenttree remote list              # List available hosts
agenttree remote start my-pc 1     # Start a task on a remote agent
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `agenttree init` | Initialize a project with `.agenttree.yaml` |
| `agenttree setup 1 2 3` | Create worktrees for agents |
| `agenttree start <id> <issue>` | Assign an issue to an agent |
| `agenttree start` | Launch server, agents, and web dashboard |
| `agenttree status` | Show all agents with stage progress |
| `agenttree attach <id>` | Attach to an agent's tmux session |
| `agenttree send <id> "msg"` | Send a message to a running agent |
| `agenttree output <id>` | View an agent's terminal output |
| `agenttree stop <id>` | Stop an agent |
| `agenttree approve <id>` | Advance an issue past a review stage |
| `agenttree auto-merge <pr>` | Merge a PR when CI passes |
| `agenttree issue create "title"` | Create a new issue |
| `agenttree notes show <id>` | Show agent's task logs |
| `agenttree notes search "query"` | Search across all notes |

## Dependencies

**Required:**
- Python 3.10+
- git (with worktree support)
- tmux
- gh (GitHub CLI)

**AI tools** (at least one):
- `claude` — Claude Code
- `aider` — Aider
- `gemini` — Gemini CLI
- Or any custom CLI tool

**Optional:**
- Docker / OrbStack / Podman (for container mode)
- Tailscale (for remote agents)

## Install from source

```bash
git clone https://github.com/davefowler/agenttree
cd agenttree
uv sync

# Run tests
uv run pytest

# Type check
uv run mypy agenttree
```

## License

MIT — see [LICENSE](LICENSE).
