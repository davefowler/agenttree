# AgentTree: Multi-Agent Development Framework

**Status**: Planning → Ready for new repo  
**Goal**: Orchestrate multiple AI coding agents across git worktrees

---

## What This Is

AgentTree lets you run **multiple AI coding agents in parallel** on the same codebase. Each agent gets its own git worktree, tmux session, and isolated environment. You dispatch GitHub issues or ad-hoc tasks to agents, and they work independently.

```
┌─────────────────────────────────────────────────────────────────┐
│                         Your Machine                             │
├─────────────────────────────────────────────────────────────────┤
│  Main Repo (you + Cursor)      │  Worktrees (Agents)            │
│  ~/Projects/myapp/             │  ~/Projects/worktrees/         │
│  ├── src/                      │  ├── agent-1/ (Claude Code)    │
│  ├── tests/                    │  ├── agent-2/ (Aider)          │
│  └── agents/  ←── shared ───→  │  └── agent-3/ (Claude Code)    │
│      ├── specs/                │                                 │
│      └── notes/                │  Each has own venv, DB, PORT   │
└─────────────────────────────────────────────────────────────────┘
```

**Workflow:**
1. You file a GitHub issue (or write a spec)
2. Run: `agenttree dispatch 1 42` (send issue #42 to agent-1)
3. Agent-1's worktree resets to latest main
4. Claude Code starts in a tmux session
5. Agent works on the issue, creates PR
6. CI is automatically monitored
7. Issue auto-closes when PR merges

---

## Why This Exists (Problem Statement)

**The problems we're solving:**

1. **Single-threaded development** - You can only work on one thing at a time with Cursor/Claude Code
2. **Context switching** - Switching between issues loses context
3. **Agent interference** - Multiple agents can't work on the same repo simultaneously
4. **CI blind spots** - Agents push code but don't check if CI passes
5. **Lost knowledge** - Agent learnings disappear after each session
6. **No orchestration** - No way to dispatch work to agents programmatically

**What exists today:**

| Tool | What it does | Limitation |
|------|-------------|------------|
| Claude Code | Single-agent coding CLI | One at a time, no dispatch |
| Aider | Single-agent coding CLI | One at a time, no dispatch |
| Cursor | AI-enhanced IDE | Single workspace focus |
| Devin | Autonomous agent | $500/mo, cloud-only, closed |
| OpenHands | Autonomous agent | Heavy, Docker, single agent |

**AgentTree's niche:**
> "Orchestrate multiple local AI coding agents (Claude Code, Aider, etc.) across git worktrees with GitHub integration, CI monitoring, and shared context."

---

## Core Concepts

### 1. Git Worktrees
Each agent gets its own worktree - a separate checkout of the same repo. They share git history but have isolated files.

```bash
# Main repo
~/Projects/myapp/

# Agent worktrees (same .git, different checkouts)
~/Projects/worktrees/agent-1/
~/Projects/worktrees/agent-2/
```

### 2. tmux Sessions
Each agent runs in a named tmux session. You can:
- Attach to watch/interact: `agenttree attach 1`
- Send messages: `agenttree send 1 "focus on tests"`
- Detach: `Ctrl+B, D`

### 3. Task Dispatch
```bash
# From GitHub issue
agenttree dispatch 1 42

# Ad-hoc task  
agenttree dispatch 2 --task "Fix the login bug"

# With specific tool
agenttree dispatch 3 42 --tool aider
```

### 4. Agent Status
```
$ agenttree status

Agent 1: 🔴 Busy - #42 Fix login validation
Agent 2: 🟢 Available
Agent 3: 🔴 Busy - #45 Add dark mode
```

### 5. Busy Detection
An agent is "busy" if:
- It has a `TASK.md` file (unfinished work), OR
- It has uncommitted git changes

### 6. CI Monitoring
After creating a PR, `submit.sh` automatically:
- Polls GitHub every 30s for CI status
- Reports success/failure to the agent
- Agent can fix and push again if CI fails

---

## Reference Implementation (Working Scripts)

These scripts work today in the dataface repo. Copy them to start.

### scripts/setup-worktree.sh

Creates a single agent worktree with venv, database, and PORT configuration.

```bash
#!/bin/bash
# Setup a single worktree for an agent
#
# Usage:
#   ./scripts/setup-worktree.sh <agent_number>
#
# Examples:
#   ./scripts/setup-worktree.sh 1   # Create agent-1
#   ./scripts/setup-worktree.sh 2   # Create agent-2

set -e

AGENT_NUM="$1"

if [ -z "$AGENT_NUM" ]; then
    echo "Usage: $0 <agent_number>"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_REPO="$(dirname "$SCRIPT_DIR")"
WORKTREES_DIR="$HOME/Projects/worktrees"
WORKTREE_PATH="$WORKTREES_DIR/agent-$AGENT_NUM"
BRANCH_NAME="agent-$AGENT_NUM-work"
AGENT_PORT="800$AGENT_NUM"

echo "==================================="
echo "Setting up Agent $AGENT_NUM"
echo "==================================="
echo "Main repo:  $MAIN_REPO"
echo "Worktree:   $WORKTREE_PATH"
echo "Branch:     $BRANCH_NAME"
echo "Port:       $AGENT_PORT"
echo ""

if [ -d "$WORKTREE_PATH" ]; then
    echo "❌ Worktree already exists: $WORKTREE_PATH"
    echo "To recreate: git worktree remove $WORKTREE_PATH"
    exit 1
fi

mkdir -p "$WORKTREES_DIR"
cd "$MAIN_REPO"

# Create branch and worktree
git branch "$BRANCH_NAME" HEAD 2>/dev/null || echo "  Branch exists"
git worktree add "$WORKTREE_PATH" "$BRANCH_NAME"

# Copy and configure .env
if [ -f "$MAIN_REPO/.env" ]; then
    cp "$MAIN_REPO/.env" "$WORKTREE_PATH/.env"
fi
# Set agent-specific PORT
if grep -q "^PORT=" "$WORKTREE_PATH/.env" 2>/dev/null; then
    sed -i.bak "s/^PORT=.*/PORT=$AGENT_PORT/" "$WORKTREE_PATH/.env"
    rm -f "$WORKTREE_PATH/.env.bak"
else
    echo "PORT=$AGENT_PORT" >> "$WORKTREE_PATH/.env"
fi

# Setup Python environment (customize for your project)
cd "$WORKTREE_PATH"
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]"  # Adjust for your project

deactivate

echo ""
echo "✅ Agent $AGENT_NUM ready at $WORKTREE_PATH"
```

### scripts/dispatch.sh

Dispatches a task to an agent. Resets worktree, creates TASK.md, starts Claude/Aider in tmux.

```bash
#!/bin/bash
# Dispatch a task to an agent
#
# Usage:
#   ./scripts/dispatch.sh <agent_number> <issue_number>
#   ./scripts/dispatch.sh <agent_number> --task "Ad-hoc task"
#   ./scripts/dispatch.sh <agent_number> --tool aider 42

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse arguments
AGENT_NUM=""
ISSUE_NUM=""
TASK_DESC=""
AI_TOOL="${AI_TOOL:-claude}"
NO_RESET=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --task)
            TASK_DESC="$2"
            shift 2
            ;;
        --tool)
            AI_TOOL="$2"
            shift 2
            ;;
        --no-reset)
            NO_RESET=true
            shift
            ;;
        *)
            if [ -z "$AGENT_NUM" ]; then
                AGENT_NUM="$1"
            else
                ISSUE_NUM="$1"
            fi
            shift
            ;;
    esac
done

WORKTREES_DIR="$HOME/Projects/worktrees"
WORKTREE_PATH="$WORKTREES_DIR/agent-$AGENT_NUM"
TMUX_SESSION="agent-$AGENT_NUM"

# Validate
if [ -z "$AGENT_NUM" ]; then
    echo "Usage: $0 <agent_number> <issue_number>"
    echo "       $0 <agent_number> --task \"description\""
    exit 1
fi

if [ ! -d "$WORKTREE_PATH" ]; then
    echo "❌ Agent $AGENT_NUM not found. Run: ./scripts/setup-worktree.sh $AGENT_NUM"
    exit 1
fi

# Check if agent is busy
cd "$WORKTREE_PATH"
HAS_TASK=false
HAS_UNCOMMITTED=false
[ -f "TASK.md" ] && HAS_TASK=true
[ "$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')" != "0" ] && HAS_UNCOMMITTED=true

if [ "$NO_RESET" = true ]; then
    echo "Keeping existing work (--no-reset)"
elif [ "$HAS_TASK" = true ] || [ "$HAS_UNCOMMITTED" = true ]; then
    echo "⚠️  Agent $AGENT_NUM appears busy:"
    [ "$HAS_TASK" = true ] && echo "   - Has unfinished TASK.md"
    [ "$HAS_UNCOMMITTED" = true ] && echo "   - Has uncommitted changes"
    echo ""
    read -p "Reset and overwrite? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Kill existing tmux session
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true

# Reset to latest main
if [ "$NO_RESET" = false ]; then
    echo "Resetting to latest main..."
    cd "$WORKTREE_PATH"
    git fetch origin
    git checkout main 2>/dev/null || git checkout -b main origin/main
    git reset --hard origin/main
    git clean -fd
    rm -f TASK.md
fi

# Create TASK.md
TASK_FILE="$WORKTREE_PATH/TASK.md"

if [ -n "$TASK_DESC" ]; then
    cat > "$TASK_FILE" << EOF
# Task

$TASK_DESC

## Workflow

\`\`\`bash
git checkout -b feature/descriptive-name
# ... implement changes ...
git commit -m "Your message"
./scripts/submit.sh --no-issue
\`\`\`
EOF
    echo "✅ Ad-hoc task created"

elif [ -n "$ISSUE_NUM" ]; then
    ISSUE_TITLE=$(gh issue view "$ISSUE_NUM" --json title -q '.title')
    ISSUE_URL=$(gh issue view "$ISSUE_NUM" --json url -q '.url')

    cat > "$TASK_FILE" << EOF
# Task: $ISSUE_TITLE

**Issue:** [#$ISSUE_NUM]($ISSUE_URL)

## Workflow

\`\`\`bash
git checkout -b issue-$ISSUE_NUM
# ... implement changes ...
git commit -m "Your message (Fixes #$ISSUE_NUM)"
./scripts/submit.sh
\`\`\`
EOF
    gh issue edit "$ISSUE_NUM" --add-label "agent-$AGENT_NUM" 2>/dev/null || true
    echo "✅ Task for issue #$ISSUE_NUM created"
else
    echo "❌ Need an issue number or --task"
    exit 1
fi

# Save agent config
cat > "$WORKTREE_PATH/.agent-config" << EOF
AI_TOOL="$AI_TOOL"
AGENT_NUM="$AGENT_NUM"
EOF

# Copy startup script
cp "$SCRIPT_DIR/agent-start.sh" "$WORKTREE_PATH/agent-start.sh"
chmod +x "$WORKTREE_PATH/agent-start.sh"

# Start tmux session
echo ""
echo "Starting $AI_TOOL in tmux: $TMUX_SESSION"
tmux new-session -d -s "$TMUX_SESSION" -c "$WORKTREE_PATH"
tmux send-keys -t "$TMUX_SESSION" "./agent-start.sh" Enter

# Send initial prompt
sleep 3
case "$AI_TOOL" in
    claude)
        tmux send-keys -t "$TMUX_SESSION" "Check TASK.md and start working on it." Enter
        ;;
    aider)
        tmux send-keys -t "$TMUX_SESSION" "/read TASK.md" Enter
        ;;
esac

echo ""
echo "Commands:"
echo "  ./scripts/agents.sh $AGENT_NUM    # Attach to session"
echo "  ./scripts/agents.sh status        # All agent status"
echo "  Ctrl+B, D                          # Detach from session"
```

### scripts/agents.sh

Manage agent sessions - list, attach, send commands, kill.

```bash
#!/bin/bash
# Manage agent tmux sessions
#
# Usage:
#   ./scripts/agents.sh                     # List all
#   ./scripts/agents.sh <n>                 # Attach to agent-n
#   ./scripts/agents.sh status              # Status of all agents
#   ./scripts/agents.sh send <n> "message"  # Send input to agent
#   ./scripts/agents.sh kill <n>            # Kill agent session

WORKTREES_DIR="$HOME/Projects/worktrees"

case "$1" in
    ""|"ls"|"list")
        echo "Agent Sessions:"
        echo ""
        for session in $(tmux ls 2>/dev/null | grep "^agent-" | cut -d: -f1); do
            TASK_FILE="$WORKTREES_DIR/$session/TASK.md"
            if [ -f "$TASK_FILE" ]; then
                TASK=$(head -1 "$TASK_FILE" | sed 's/# //')
            else
                TASK="(no task)"
            fi
            echo "  $session: $TASK"
        done
        if ! tmux ls 2>/dev/null | grep -q "^agent-"; then
            echo "  No agent sessions running"
        fi
        echo ""
        echo "Commands:"
        echo "  ./scripts/agents.sh <n>              # Attach"
        echo "  ./scripts/agents.sh send <n> \"msg\"   # Send input"
        echo "  ./scripts/agents.sh kill <n>         # Kill"
        ;;

    "status")
        echo "Agent Status:"
        echo ""
        for i in 1 2 3 4 5; do
            SESSION="agent-$i"
            WORKTREE="$WORKTREES_DIR/$SESSION"
            if [ -d "$WORKTREE" ]; then
                TASK_FILE="$WORKTREE/TASK.md"
                HAS_TASK=false
                [ -f "$TASK_FILE" ] && HAS_TASK=true
                cd "$WORKTREE"
                HAS_UNCOMMITTED=$([ "$(git status --porcelain 2>/dev/null | wc -l)" != "0" ] && echo true || echo false)

                if [ "$HAS_TASK" = true ]; then
                    TASK=$(grep -m1 "^# Task" "$TASK_FILE" | sed 's/^# //')
                    [ "$TASK" = "Task" ] && TASK=$(sed -n '3p' "$TASK_FILE" | head -c 50)
                    if tmux has-session -t "$SESSION" 2>/dev/null; then
                        STATUS="🔴 Busy"
                    else
                        STATUS="🟡 Has task"
                    fi
                elif [ "$HAS_UNCOMMITTED" = true ]; then
                    STATUS="🟡 Uncommitted"
                    TASK=""
                else
                    STATUS="🟢 Available"
                    TASK=""
                fi
                echo "  Agent $i: $STATUS"
                [ -n "$TASK" ] && echo "           $TASK"
            fi
        done
        ;;

    "send")
        SESSION="agent-$2"
        tmux send-keys -t "$SESSION" "$3" Enter && echo "Sent to $SESSION"
        ;;

    "kill")
        tmux kill-session -t "agent-$2" 2>/dev/null && echo "Killed agent-$2"
        ;;

    "kill-all")
        for session in $(tmux ls 2>/dev/null | grep "^agent-" | cut -d: -f1); do
            tmux kill-session -t "$session"
            echo "Killed $session"
        done
        ;;

    *)
        SESSION="agent-$1"
        if tmux has-session -t "$SESSION" 2>/dev/null; then
            echo "Attaching to $SESSION (Ctrl+B, D to detach)..."
            tmux attach -t "$SESSION"
        else
            echo "Session $SESSION not found"
            echo "Start with: ./scripts/dispatch.sh $1 <issue>"
        fi
        ;;
esac
```

### scripts/agent-start.sh

Startup script that runs in each agent's tmux session.

```bash
#!/bin/bash
# Agent startup script - runs when tmux session starts

set -e

WORKTREE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$WORKTREE_ROOT"

# Activate venv
[ -f ".venv/bin/activate" ] && source .venv/bin/activate
[ -f "venv/bin/activate" ] && source venv/bin/activate

# Load .env
[ -f ".env" ] && export $(grep -v '^#' .env | xargs)

# Read agent config
AI_TOOL="${AI_TOOL:-claude}"
[ -f ".agent-config" ] && source .agent-config

echo "================================"
echo "Agent Starting"
echo "================================"
echo "Worktree: $WORKTREE_ROOT"
echo "AI Tool:  $AI_TOOL"
echo ""

[ -f "TASK.md" ] && echo "📋 Task:" && head -5 TASK.md && echo ""

# Start AI tool
case "$AI_TOOL" in
    claude) claude ;;
    aider)  aider ;;
    codex)  codex ;;
    *)      $AI_TOOL ;;
esac
```

### scripts/submit.sh

Push work, create PR, and monitor CI.

```bash
#!/bin/bash
# Submit completed work: push branch and create PR
# Automatically monitors CI status after PR creation

set -e

REPO_ROOT=$(git rev-parse --show-toplevel)
cd "$REPO_ROOT"

ISSUE_NUM="$1"

# Try to get issue from TASK.md
if [ -z "$ISSUE_NUM" ] && [ -f "TASK.md" ]; then
    ISSUE_NUM=$(grep -oE '#[0-9]+' TASK.md | head -1 | tr -d '#')
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)

if [ "$BRANCH" = "main" ] || [ "$BRANCH" = "master" ]; then
    echo "❌ You're on $BRANCH. Create a feature branch first."
    exit 1
fi

# Handle uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
    echo "⚠️  Uncommitted changes:"
    git status --short
    echo ""
    read -p "Commit all? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        read -p "Commit message: " MSG
        git add -A
        if [ -n "$ISSUE_NUM" ] && [ "$ISSUE_NUM" != "--no-issue" ]; then
            git commit -m "$MSG (Fixes #$ISSUE_NUM)"
        else
            git commit -m "$MSG"
        fi
    else
        echo "Commit first, then run again."
        exit 1
    fi
fi

# Push
echo "Pushing $BRANCH..."
git push -u origin "$BRANCH"

# Create PR
echo "Creating PR..."
if [ -n "$ISSUE_NUM" ] && [ "$ISSUE_NUM" != "--no-issue" ]; then
    ISSUE_TITLE=$(gh issue view "$ISSUE_NUM" --json title -q '.title' 2>/dev/null || echo "")
    PR_TITLE="${ISSUE_TITLE:-$BRANCH}"
    PR_BODY="Fixes #$ISSUE_NUM"
    PR_URL=$(gh pr create --title "$PR_TITLE" --body "$PR_BODY" 2>&1)
else
    PR_URL=$(gh pr create --fill 2>&1)
fi

echo ""
echo "✅ PR created: $PR_URL"

# Clean up TASK.md
[ -f "TASK.md" ] && rm "TASK.md" && echo "Removed TASK.md"

# Monitor CI
PR_NUM=$(echo "$PR_URL" | grep -oE '[0-9]+$')
echo ""
echo "Waiting for CI (every 30s, max 10 min)..."

MAX_WAIT=600
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    sleep 30
    ELAPSED=$((ELAPSED + 30))
    
    STATUS=$(gh pr checks "$PR_NUM" --json state 2>/dev/null || echo "[]")
    
    if echo "$STATUS" | grep -q '"state":"PENDING"'; then
        echo "  ⏳ CI running... ($ELAPSED s)"
        continue
    fi
    
    if echo "$STATUS" | grep -q '"state":"FAILURE"'; then
        echo ""
        echo "❌ CI FAILED!"
        gh pr checks "$PR_NUM"
        echo ""
        echo "Fix and push again."
        exit 1
    fi
    
    if echo "$STATUS" | grep -q '"state":"SUCCESS"'; then
        echo ""
        echo "✅ CI passed!"
        exit 0
    fi
done

echo "⏰ CI still running - check: gh pr checks $PR_NUM"
```

---

## agents/ Directory: Shared AI Context

A separate git repo inside your project for all AI-generated content.

```
project/
├── .git/                      # Main project repo
├── agents/                    # Separate git repo
│   ├── .git/
│   ├── specs/                 # Feature specifications
│   │   └── issue-42-login-fix.md
│   ├── plans/                 # Architecture, research
│   │   └── api-redesign.md
│   ├── notes/                 # Agent learnings
│   │   └── agent-1-notes.md
│   └── templates/             # Spec templates
│       └── feature-spec.md
```

### Auto-sync on git pull

Add a post-merge hook to sync agents/ when pulling main repo:

```bash
# .git/hooks/post-merge
#!/bin/bash
if [ -d "agents/.git" ]; then
    echo "Syncing agents/..."
    cd agents && git pull origin main
fi
```

### Spec-Driven Workflow

Instead of TASK.md, write specs in agents/:

1. Create `agents/specs/issue-42-login-fix.md`
2. Commit & push to agents/ repo
3. Dispatch: `agenttree dispatch 1 42 --spec`
4. Agent pulls agents/, finds their spec
5. Agent updates spec with implementation notes
6. Spec becomes permanent documentation

---

## Web Dashboard (Future)

Chat with agents from your phone using web terminals:

```bash
# Install ttyd (terminal to web)
brew install ttyd

# Expose agent session
ttyd -p 7681 tmux attach -t agent-1
```

**Options:**
- [ttyd](https://github.com/tsl0922/ttyd) - Simple, C-based
- [gotty](https://github.com/yudai/gotty) - Go-based
- [wetty](https://github.com/butlerx/wetty) - Node.js
- Tailscale SSH in browser

---

## Remote Agents (Tailscale)

Run agents on other machines:

```yaml
# .agenttree/agents.yaml
agents:
  remote:
    - id: remote-1
      host: build-server.tailnet.ts.net
      ssh_user: agent
```

Dispatch to remote:
```bash
agenttree dispatch remote-1 42
# SSHs to remote machine and runs dispatch there
```

---

## Local LLMs (Aider Hybrid)

Use Claude for planning, local LLM for execution:

```bash
aider --architect \
  --model ollama/qwen2.5-coder:32b \
  --editor-model anthropic/claude-sonnet-4-20250514
```

**90%+ cost reduction** while maintaining quality.

---

## Containerization (for dangerous mode)

Running agents with `--dangerously-skip-permissions` lets them execute any command without approval. **This is risky** - a hallucinating agent could `rm -rf /` or leak secrets. Containers provide isolation.

### Apple Container (macOS 26+)

Apple Container uses `Virtualization.framework` to run each container in a **lightweight VM**, not just process isolation. This is stronger than Docker's namespace isolation.

**Isolation level:**
- ✅ Full filesystem isolation (VM has its own filesystem)
- ✅ Network isolation (can be configured)
- ✅ Process isolation (completely separate kernel)
- ✅ No access to host secrets/credentials
- ✅ Agent can't damage host system even with `rm -rf /`

**Is it enough for dangerous mode?** Yes - Apple Container's VM isolation is sufficient. The agent can do anything inside the container but can't escape to the host.

```bash
# With Apple Container (macOS 26+)
container run -it --rm \
  -v "$(pwd):/workspace" \
  -w /workspace \
  ghcr.io/agenttree/agent-runtime:latest \
  claude --dangerously-skip-permissions
```

### Docker (macOS < 26, Linux, Windows)

Docker uses namespace isolation (shared kernel), which is weaker than VM isolation but still very good for our use case.

**Isolation level:**
- ✅ Filesystem isolation (container has its own root)
- ✅ Process isolation (PID namespace)
- ⚠️ Shared kernel (theoretical escape vectors, rare in practice)
- ✅ Agent can't access host files (unless explicitly mounted)

**Is it enough for dangerous mode?** Yes, for practical purposes. While Docker isolation is technically weaker than VM isolation, kernel escapes are rare and the agent would need to be intentionally malicious.

```bash
# With Docker
docker run -it --rm \
  -v "$(pwd):/workspace" \
  -w /workspace \
  ghcr.io/agenttree/agent-runtime:latest \
  claude --dangerously-skip-permissions
```

### Cross-Platform Strategy

| Platform | Container Runtime | Notes |
|----------|------------------|-------|
| **macOS 26+** | Apple Container | Native, VM isolation, recommended |
| **macOS < 26** | Docker | Works fine, just update your OS already 😄 |
| **Linux** | Docker / Podman | Native containers, excellent support |
| **Windows** | Docker Desktop / WSL2 | Docker Desktop or run in WSL2 |

### Linux Users

Docker is native on Linux - containers share the host kernel, which is actually how Docker was designed to work. Excellent performance and isolation.

```bash
# Ubuntu/Debian
sudo apt install docker.io
sudo usermod -aG docker $USER

# Or use Podman (daemonless, rootless)
sudo apt install podman
alias docker=podman
```

### Windows Users

Two options:

1. **Docker Desktop** - GUI, easy setup, but requires license for commercial use
2. **WSL2 + Docker** - Run Linux in WSL2, use Docker there (recommended)

```powershell
# Option 1: Docker Desktop
winget install Docker.DockerDesktop

# Option 2: WSL2 (free, better for dev)
wsl --install -d Ubuntu
# Then install Docker inside Ubuntu
```

**Note:** Claude Code CLI currently requires macOS/Linux. Windows users should use WSL2 anyway for the best experience.

### Comparison Table

| Feature | Apple Container | Docker (Linux) | Docker (Windows) |
|---------|----------------|----------------|------------------|
| **Isolation** | VM | Namespace | VM (Hyper-V) |
| **Performance** | Excellent | Excellent | Good |
| **Setup** | `brew install` | Native | Docker Desktop or WSL2 |
| **Commercial use** | Free | Free | Docker Desktop license required* |
| **Dangerous mode safe?** | ✅ Yes | ✅ Yes | ✅ Yes |

*Docker Desktop is free for personal use and small businesses

### Implementation in AgentTree

**Strategy:** Detect platform and use best available runtime.

```python
# agenttree/container.py
import shutil
import subprocess
import platform

def get_container_runtime() -> str:
    """Detect available container runtime based on platform"""
    system = platform.system()
    
    if system == "Darwin":  # macOS
        if shutil.which("container"):  # Apple Container (macOS 26+)
            return "container"
        elif shutil.which("docker"):
            return "docker"
        else:
            raise RuntimeError("Install Docker or upgrade to macOS 26+")
    
    elif system == "Linux":
        if shutil.which("docker"):
            return "docker"
        elif shutil.which("podman"):
            return "podman"  # Podman is Docker-compatible
        else:
            raise RuntimeError("Install Docker: sudo apt install docker.io")
    
    elif system == "Windows":
        if shutil.which("docker"):
            return "docker"
        else:
            raise RuntimeError("Install Docker Desktop or use WSL2")

def run_in_container(
    worktree_path: str,
    ai_tool: str = "claude",
    dangerous: bool = True
) -> subprocess.Popen:
    """Run AI tool in isolated container"""
    runtime = get_container_runtime()
    
    cmd = [
        runtime, "run", "-it", "--rm",
        "-v", f"{worktree_path}:/workspace",
        "-w", "/workspace",
        "ghcr.io/agenttree/agent-runtime:latest",
    ]
    
    if dangerous:
        cmd.extend([ai_tool, "--dangerously-skip-permissions"])
    else:
        cmd.append(ai_tool)
    
    return subprocess.Popen(cmd)
```

### Agent Runtime Image

We'll publish a Docker/Container image with all AI tools pre-installed:

```dockerfile
# Dockerfile for ghcr.io/agenttree/agent-runtime
FROM python:3.11-slim

# Install AI tools
RUN pip install anthropic aider-chat

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Install common dev tools
RUN apt-get update && apt-get install -y git gh tmux

# Install Codex (if available)
# RUN npm install -g @openai/codex

WORKDIR /workspace
```

### Implementation Complexity

| Component | Effort | Notes |
|-----------|--------|-------|
| Runtime detection | Easy | Just check `which container` vs `which docker` |
| Container execution | Easy | Same CLI pattern for both |
| Volume mounting | Easy | `-v $(pwd):/workspace` works for both |
| Published image | Medium | Need to build & publish to ghcr.io |
| CI for image | Medium | GitHub Actions to build on each release |
| GPU passthrough | Hard | Different for Docker vs Apple Container |

**Total additional effort:** ~1 week to add container support with fallback.

### Dispatch with Container Mode

```bash
# Normal mode (interactive, with approvals)
agenttree dispatch 1 42

# Autonomous mode in container (dangerous but isolated)
agenttree dispatch 1 42 --container --dangerous

# Or set as default in config
# .agenttree.yaml
# default_mode: container
# dangerous: true
```

### When to Use Containers

| Scenario | Recommendation |
|----------|---------------|
| Watching agent work | No container needed |
| Trusted small tasks | No container needed |
| Large autonomous tasks | Use container |
| Running overnight | Use container |
| Untrusted codebases | Use container |
| CI/automated dispatch | Always use container |

### Security Recommendations

1. **Mount only the worktree**, not your whole home directory
2. **Don't mount ~/.ssh or ~/.aws** into containers
3. **Use read-only mounts** for reference files: `-v ~/reference:/ref:ro`
4. **Network isolation** for sensitive work: `--network none`
5. **Resource limits**: `--memory 8g --cpus 4`

```bash
# Maximum isolation example
docker run -it --rm \
  --network none \
  --memory 8g \
  --cpus 4 \
  -v "$(pwd):/workspace" \
  -v "$HOME/.gitconfig:/root/.gitconfig:ro" \
  ghcr.io/agenttree/agent-runtime:latest \
  claude --dangerously-skip-permissions
```

---

## Configuration

```yaml
# .agenttree.yaml
project: myapp                           # Namespace for tmux sessions
worktrees_dir: ~/Projects/worktrees      # Where to create worktrees
port_range: 8001-8009                     # Ports for agents

default_tool: claude

tools:
  claude:
    command: claude
    startup_prompt: "Check TASK.md and start working."
    
  aider:
    command: aider --model sonnet
    startup_prompt: "/read TASK.md"
```

---

## Package Structure (pip install agenttree)

```
agenttree/
├── cli.py              # CLI (agenttree dispatch, status, etc.)
├── config.py           # Configuration loading
├── worktree.py         # Git worktree management
├── tmux.py             # Tmux session management
├── github.py           # GitHub API (issues, PRs, CI)
├── agents/
│   ├── base.py         # BaseAgent interface
│   ├── claude.py       # Claude Code adapter
│   ├── aider.py        # Aider adapter
│   └── codex.py        # Codex adapter
├── remote/
│   ├── registry.py     # Agent registry
│   └── tailscale.py    # Remote dispatch
└── server/
    ├── app.py          # FastAPI dashboard
    └── templates/      # Web UI
```

---

## CLI Commands (Target)

```bash
# Initialize in a repo
agenttree init

# Setup agents
agenttree setup 1 2 3

# Dispatch
agenttree dispatch 1 42
agenttree dispatch 2 --task "Fix bug"
agenttree dispatch remote-1 42

# Management
agenttree status
agenttree attach 1
agenttree send 1 "focus on tests"
agenttree kill 1
agenttree logs 1

# Server
agenttree serve
```

---

## Implementation Roadmap

### Phase 1: Core Package (Week 1-2)
- [ ] Port bash scripts to Python CLI
- [ ] Add configuration system (.agenttree.yaml)
- [ ] Namespace isolation (project prefix)
- [ ] PyPI release

### Phase 2: Agent Adapters (Week 3)
- [ ] BaseAgent interface
- [ ] Claude Code, Aider, Codex adapters
- [ ] Custom command support

### Phase 3: agents/ Repo (Week 4)
- [ ] Init command creates agents/ git repo
- [ ] Post-merge hook setup
- [ ] Spec-driven dispatch

### Phase 4: Remote Agents (Week 5)
- [ ] Agent registry (.agenttree/agents.yaml)
- [ ] Tailscale discovery
- [ ] SSH dispatch

### Phase 5: Dashboard (Week 6-7)
- [ ] FastAPI server
- [ ] Web terminal (ttyd integration)
- [ ] Real-time status

---

## Dependencies

**Required:**
- Python 3.10+
- git (with worktree support)
- tmux
- gh (GitHub CLI)

**Optional:**
- ttyd (web terminal)
- Docker/OrbStack (container mode)
- Tailscale (remote agents)

**AI Tools (pick one or more):**
- claude (Claude Code CLI)
- aider
- codex

---

## Quick Start (For New Repo)

```bash
# 1. Copy the scripts/ folder from above

# 2. Setup first agent
./scripts/setup-worktree.sh 1

# 3. Create a GitHub issue or use ad-hoc task
./scripts/dispatch.sh 1 --task "Add user authentication"

# 4. Watch the agent work
./scripts/agents.sh 1

# 5. When done, agent runs:
./scripts/submit.sh
```

---

## .gitignore additions

```
TASK.md
.agent-config
agents/  # If using separate repo (or don't ignore if keeping in main)
```

---

## AGENTS.md (for Claude Code / AI tools)

Put this in your repo root so AI tools understand the setup:

```markdown
# Agent Configuration

## If you have a TASK.md file, read it first - you have an assigned task!

## Rules
See @.cursorrules for coding guidelines.

## Task Workflow
1. Read TASK.md for your assignment
2. Create feature branch: `git checkout -b issue-<number>`
3. Implement changes following project conventions
4. Include `Fixes #<number>` in commit messages
5. Run: `./scripts/submit.sh` to push and create PR

## Available Scripts
- `./scripts/submit.sh` - Push and create PR (monitors CI)
- `./ci` - Run full CI check locally
```

---

## Questions for Development

1. **Package name**: `agenttree` or something else?
2. **agents/ repo location**: Inside project or separate?
3. **Default tool**: Claude Code, Aider, or configurable?
4. **Namespace scheme**: `{project}-agent-{n}` or simpler?

---

## See Also

- [Aider](https://github.com/paul-gauthier/aider) - AI pair programming
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - Anthropic's CLI
- [ttyd](https://github.com/tsl0922/ttyd) - Terminal to web
- [git worktree docs](https://git-scm.com/docs/git-worktree)
