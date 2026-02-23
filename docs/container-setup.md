# Container Setup Guide

AgentTree runs AI coding agents in isolated containers for security. This guide covers setup and common issues.

## Quick Start

1. **Install a container runtime** (Docker or Apple Container)
   ```bash
   # Check if available
   agenttree start 1 --dry-run
   ```

2. **Build the container image** (first time only)
   ```bash
   docker build -t agenttree-agent .
   ```

3. **Start an agent**
   ```bash
   agenttree start 23  # Creates container for issue #23
   ```

## How It Works

When you run `agenttree start <issue>`:

1. **Worktree created**: `.worktrees/issue-023-fix-login/`
2. **Branch created**: `issue-023-fix-login`
3. **Container started**: `agenttree-issue-023`
4. **Tmux session**: For attaching/sending messages
5. **Port allocated**: Dynamic from pool (3001, 3002, etc.)

When the issue moves to `accepted`, everything is automatically cleaned up.

## Container Architecture

```
┌─────────────────────────────────────────┐
│ Container: agenttree-issue-023          │
│                                         │
│  /workspace (mounted from worktree)     │
│  ├── .git (file → main repo's .git)     │
│  ├── TASK.md                            │
│  ├── CLAUDE.md                          │
│  └── ... project files                  │
│                                         │
│  Claude CLI running with auto-skip      │
│  permissions (safe - isolated)          │
└─────────────────────────────────────────┘
        │
        ▼ Mounts
┌─────────────────────────────────────────┐
│ Host                                    │
│  .worktrees/issue-023-fix-login/        │
│  .git/ (main repo)                      │
│  ~/.claude/ (optional - for API key)    │
└─────────────────────────────────────────┘
```

## Dockerfile Requirements

Your Dockerfile should:

```dockerfile
FROM python:3.11-slim

# Install git and dependencies
RUN apt-get update && apt-get install -y git curl

# Install Claude CLI
RUN curl -fsSL https://claude.ai/install.sh | sh

# Pre-seed Claude config (skip onboarding wizard)
RUN mkdir -p /home/agent/.claude && \
    echo '{"hasCompletedOnboarding":true}' > /home/agent/.claude.json && \
    echo '{"theme":"dark"}' > /home/agent/.claude/settings.json

# Install agenttree
COPY . /opt/agenttree
RUN uv pip install --system -e /opt/agenttree

WORKDIR /workspace
```

## Common Issues

### 1. Claude CLI Onboarding Wizard

**Problem**: First-run wizard appears on every container restart.

**Solution**: Pre-seed config in Dockerfile:
```dockerfile
RUN echo '{"hasCompletedOnboarding":true}' > /home/agent/.claude.json
```

### 2. Git Worktrees Don't Work

**Problem**: Git worktrees use absolute paths that don't exist in container.

**Solution**: AgentTree automatically mounts the main `.git` directory at the same path:
```python
# Handled in container.py
cmd.extend(["-v", f"{main_git_dir}:{main_git_dir}"])
```

### 3. Can't Push to Git

**Problem**: No SSH keys or credentials in container.

**Solutions**:
1. **Mount SSH keys** (if using SSH):
   ```yaml
   # .agenttree.yaml
   container:
     volumes:
       - ~/.ssh:/home/agent/.ssh:ro
   ```

2. **Use GitHub token**:
   ```bash
   export GITHUB_TOKEN=ghp_xxx
   agenttree start 23
   ```

3. **Let hooks handle it**: The PR workflow auto-pushes from the container using mounted credentials.

### 4. Dev Dependencies Missing

**Problem**: Can't run tests - pytest not installed.

**Solution**: Install dev extras in entrypoint:
```bash
uv pip install --system -e "/workspace[dev]"
```

### 5. PATH Not Available to Claude

**Problem**: Installed tools but Claude can't find them.

**Solution**: Use `exec env` in entrypoint:
```bash
exec env PATH="/new/path:${PATH}" "$@"
```

### 6. Apple Container Volume Limitations

**Problem**: Apple Container can't mount individual files, only directories.

**Solution**: Mount directory and copy files in entrypoint:
```bash
if [ -f /home/agent/.claude-host/.claude.json ]; then
    cp /home/agent/.claude-host/.claude.json /home/agent/.claude.json
fi
```

## Checking Container Status

```bash
# List active agents
agenttree agents

# Check container logs
docker logs agenttree-issue-023

# Attach to agent session
agenttree attach 23

# Send message to agent
agenttree send 23 "check git status"
```

## Cleanup

Containers are automatically cleaned up when issues move to `accepted`. For manual cleanup:

```bash
# Stop agent for an issue
agenttree kill 23

# Remove all agenttree containers
docker rm -f $(docker ps -aq --filter "name=agenttree-")

# Remove worktrees
rm -rf .worktrees/
```

## Environment Variables

Agenttree sets these env vars in every container automatically:

| Variable | Example | Description |
|----------|---------|-------------|
| `PORT` | `9042` | Assigned port for this agent's dev server |
| `AGENTTREE_CONTAINER` | `1` | Always `1` — indicates running in a container |
| `AGENTTREE_ISSUE_ID` | `42` | Issue number this agent is working on |
| `AGENTTREE_ROLE` | `developer` | Agent role (developer, reviewer, etc.) |

These are passed through from the host if configured:

| Variable | Description |
|----------|-------------|
| `GITHUB_TOKEN` | For GitHub API access (PRs, issues) |
| `CLAUDE_CODE_OAUTH_TOKEN` | OAuth token for Claude CLI (from `claude setup-token`) |
| `ANTHROPIC_API_KEY` | Anthropic API key (for rate limit fallback) |

See [commands-and-serving.md](commands-and-serving.md) for how to use these
in custom commands and the `serve` config.

## See Also

- [Troubleshooting Guide](troubleshooting.md)
- [Architecture Overview](architecture.md)
