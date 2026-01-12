# AgentTree Security Model

## Mandatory Container Isolation

**AgentTree requires containers. This is not optional.**

All agents run inside containers (Apple Container, Docker, or Podman). There is no way to disable this requirement. If no container runtime is available, AgentTree will refuse to run.

### Why Containers Are Mandatory

AI agents have significant capabilities:
- They can read and write files
- They can execute shell commands
- They can access network resources
- They can modify your system

Without isolation, a misbehaving or compromised agent could:
- Delete important files
- Access your SSH keys, credentials, API tokens
- Modify files outside the worktree
- Install malware or backdoors
- Access sensitive data

**We do not trust AI agents with unrestricted system access.**

### No Fallbacks, No Exceptions

Previous versions of AgentTree allowed running without containers using `--no-container --i-accept-the-risk`. This option has been **permanently removed**.

The reasoning:
1. **Silent fallbacks are dangerous** - If container mode fails, users might not notice
2. **"Accept the risk" is security theater** - Most users will click through warnings
3. **Consistency is key** - All agents should behave identically
4. **Defense in depth** - Containers are a critical security layer

### Supported Container Runtimes

AgentTree supports these container runtimes (checked in order):

1. **Apple Container** (macOS 26+) - `container` command
2. **Docker** - `docker` command  
3. **Podman** - `podman` command

### What If I Don't Have a Container Runtime?

Install one:

**macOS:**
```bash
# Upgrade to macOS 26+ for Apple Container (recommended)
# Or install Docker:
brew install docker
```

**Linux:**
```bash
# Docker
sudo apt install docker.io

# Or Podman
sudo apt install podman
```

**Windows:**
```bash
# Install Docker Desktop or use WSL2 with Docker
```

### Container Configuration

Agents run in containers with:
- Worktree mounted at `/workspace`
- Working directory set to `/workspace`
- `--dangerously-skip-permissions` flag (safe because container provides isolation)
- Network access (for API calls, git operations)
- No access to host filesystem outside `/workspace`

### Claude Permission Prompts

Since containers provide isolation, Claude's built-in permission prompts are redundant. AgentTree runs Claude with `--dangerously-skip-permissions` by default when `skip_permissions: true` is set in config.

This is safe because:
1. The container restricts what Claude can actually do
2. Claude can only access files in `/workspace` (the mounted worktree)
3. Any "dangerous" operations are contained within the sandbox

### Reporting Security Issues

If you find a security vulnerability in AgentTree, please report it privately. Do not open a public GitHub issue.

Contact: [security contact info]

