# Container Strategy

## Platform-Specific Approaches

### macOS: Apple Container

**Available:** macOS 26+ (Sequoia or later)

**Why Apple Container:**
- ✅ Native macOS integration (no Docker Desktop licensing)
- ✅ True VM isolation using `Virtualization.framework`
- ✅ Lightweight and fast
- ✅ Free for all users
- ✅ Better resource management than Docker Desktop

**CLI:**
```bash
# Check if available
which container

# Run container
container run -it --rm \
  -v "$PWD:/workspace" \
  -w /workspace \
  ghcr.io/agenttree/agent:latest \
  claude --dangerously-skip-permissions
```

**Detection:**
```python
def has_apple_container() -> bool:
    """Check if Apple Container is available (macOS 26+)."""
    return shutil.which("container") is not None
```

### Linux & Windows: Docker

**Why Docker:**
- ✅ De facto standard on Linux
- ✅ Native on Linux (no VM overhead)
- ✅ Wide adoption and support
- ✅ Docker Desktop on Windows (WSL2 backend)

**CLI:**
```bash
# Check if available
which docker

# Run container
docker run -it --rm \
  -v "$PWD:/workspace" \
  -w /workspace \
  ghcr.io/agenttree/agent:latest \
  claude --dangerously-skip-permissions
```

**Detection:**
```python
def has_docker() -> bool:
    """Check if Docker is available."""
    return shutil.which("docker") is not None
```

### Alternative: Podman (Linux Optional)

**Why Podman:**
- ✅ Daemonless (no Docker daemon needed)
- ✅ Rootless containers (better security)
- ✅ Docker-compatible CLI
- ✅ Open source

**When to use:**
- User prefers Podman over Docker
- Rootless containers desired
- Linux servers without Docker daemon

**Detection:**
```python
def has_podman() -> bool:
    """Check if Podman is available."""
    return shutil.which("podman") is not None
```

## Implementation Strategy

### Keep It Simple: Direct CLI Calls

**No wrapper library needed** - Just use subprocess with the right CLI tool.

```python
# agenttree/container.py (simplified)

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List


class ContainerRuntime:
    """Simple container runtime abstraction."""

    def __init__(self):
        self.runtime = self._detect()

    def _detect(self) -> Optional[str]:
        """Detect available container runtime.

        Returns:
            Runtime name or None if none available
        """
        system = platform.system()

        # macOS: Prefer Apple Container, fallback to Docker
        if system == "Darwin":
            if shutil.which("container"):
                return "container"
            elif shutil.which("docker"):
                return "docker"

        # Linux: Prefer Docker, fallback to Podman
        elif system == "Linux":
            if shutil.which("docker"):
                return "docker"
            elif shutil.which("podman"):
                return "podman"

        # Windows: Docker (via Docker Desktop or WSL2)
        elif system == "Windows":
            if shutil.which("docker"):
                return "docker"

        return None

    def is_available(self) -> bool:
        """Check if a container runtime is available."""
        return self.runtime is not None

    def run(
        self,
        image: str,
        command: List[str],
        worktree: Path,
        interactive: bool = True,
        remove: bool = True,
        **extra_args
    ) -> subprocess.CompletedProcess:
        """Run a container.

        Args:
            image: Container image to run
            command: Command to run in container
            worktree: Path to mount as /workspace
            interactive: Run in interactive mode
            remove: Remove container after exit
            **extra_args: Additional runtime-specific args

        Returns:
            Completed process

        Raises:
            RuntimeError: If no runtime available
        """
        if not self.runtime:
            raise RuntimeError(self._get_install_instructions())

        # Build command - all three runtimes have same syntax!
        cmd = [self.runtime, "run"]

        if interactive:
            cmd.extend(["-it"])

        if remove:
            cmd.append("--rm")

        # Mount worktree
        cmd.extend(["-v", f"{worktree.absolute()}:/workspace"])
        cmd.extend(["-w", "/workspace"])

        # Add extra args (e.g., --network, --memory)
        for key, value in extra_args.items():
            if value is True:
                cmd.append(f"--{key}")
            elif value is not False and value is not None:
                cmd.extend([f"--{key}", str(value)])

        # Image and command
        cmd.append(image)
        cmd.extend(command)

        # Run it
        return subprocess.run(cmd)

    def _get_install_instructions(self) -> str:
        """Get installation instructions for current platform."""
        system = platform.system()

        if system == "Darwin":
            return (
                "No container runtime found.\n\n"
                "Install options:\n"
                "  1. Apple Container (macOS 26+): Built-in, upgrade macOS\n"
                "  2. Docker Desktop: brew install --cask docker\n"
                "  3. OrbStack (lightweight): brew install --cask orbstack\n"
            )

        elif system == "Linux":
            return (
                "No container runtime found.\n\n"
                "Install Docker:\n"
                "  Ubuntu/Debian: sudo apt install docker.io\n"
                "  Fedora:        sudo dnf install docker\n"
                "  Arch:          sudo pacman -S docker\n\n"
                "Or install Podman:\n"
                "  Ubuntu/Debian: sudo apt install podman\n"
                "  Fedora:        sudo dnf install podman\n"
            )

        elif system == "Windows":
            return (
                "No container runtime found.\n\n"
                "Install Docker Desktop:\n"
                "  Download: https://www.docker.com/products/docker-desktop\n\n"
                "Or use WSL2 + Docker:\n"
                "  1. Install WSL2: wsl --install\n"
                "  2. Install Docker in WSL2 Ubuntu\n"
            )

        return "No container runtime found. Please install Docker."

    def get_runtime_name(self) -> str:
        """Get the name of the detected runtime."""
        return self.runtime or "none"


# Global instance
_runtime: Optional[ContainerRuntime] = None


def get_runtime() -> ContainerRuntime:
    """Get global container runtime instance."""
    global _runtime
    if _runtime is None:
        _runtime = ContainerRuntime()
    return _runtime
```

## Usage in AgentTree

```python
from agenttree.container import get_runtime

# Check if available
runtime = get_runtime()
if not runtime.is_available():
    print(f"Error: {runtime._get_install_instructions()}")
    sys.exit(1)

print(f"Using container runtime: {runtime.get_runtime_name()}")

# Run agent in container
runtime.run(
    image="ghcr.io/agenttree/agent:latest",
    command=["claude", "--dangerously-skip-permissions"],
    worktree=Path("/path/to/worktree"),
    interactive=True,
    remove=True,
    # Extra Docker/Podman args
    memory="8g",
    cpus="4",
    network="none",  # Isolate from network
)
```

## CLI Integration

```bash
# Dispatch with container
agenttree dispatch 1 42 --container

# Behind the scenes:
# - Detects runtime (container on macOS, docker on Linux)
# - Runs: container run -it --rm -v ... ghcr.io/agenttree/agent:latest
```

## Container Image

Build multi-platform image with all AI tools:

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh

# Install AI tools
RUN pip install --no-cache-dir \
    anthropic \
    aider-chat

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Set working directory
WORKDIR /workspace

# Default command
CMD ["bash"]
```

**Build and publish:**
```bash
# Build for multiple platforms
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/agenttree/agent:latest \
  --push .
```

## Why This Approach?

**Pros:**
- ✅ **Simple**: No complex library dependencies
- ✅ **Universal**: Same CLI syntax for all runtimes
- ✅ **Native**: Uses platform-appropriate runtime
- ✅ **Zero overhead**: Direct subprocess calls
- ✅ **Maintainable**: One simple class

**Cons:**
- ❌ No fancy Python API (but we don't need it)
- ❌ Have to parse CLI output for advanced features

**Why not use `docker-py` or `podman-py`?**
- We only need to `run` containers (not build, manage networks, etc.)
- CLI interface is simpler and more reliable
- Avoids dependency on Python libraries that might break
- All three runtimes have identical CLI syntax

## Platform Support Matrix

| Platform | Primary | Fallback | Installation |
|----------|---------|----------|--------------|
| **macOS 26+** | Apple Container | Docker Desktop | Built-in / brew |
| **macOS <26** | Docker Desktop | - | brew install --cask docker |
| **Linux** | Docker | Podman | apt/dnf/pacman |
| **Windows** | Docker Desktop | WSL2+Docker | Download installer |

## Security Considerations

### Isolation Levels

**Apple Container (macOS 26+):**
- ✅ True VM isolation
- ✅ Separate kernel
- ✅ Strongest isolation

**Docker on Linux:**
- ✅ Namespace isolation
- ⚠️ Shared kernel
- ✅ Good for practical use

**Docker Desktop (macOS/Windows):**
- ✅ VM-based (HyperKit/WSL2)
- ✅ Strong isolation
- ⚠️ Resource overhead

### Safe Defaults

```python
# Default container args for safety
SAFE_DEFAULTS = {
    "network": "none",        # No network access
    "memory": "8g",           # Limit RAM
    "cpus": "4",              # Limit CPU
    "read_only": False,       # Allow writes to workspace
}

# Only workspace is writable
runtime.run(
    image="ghcr.io/agenttree/agent:latest",
    command=["claude", "--dangerously-skip-permissions"],
    worktree=worktree_path,
    **SAFE_DEFAULTS
)
```

## Implementation Checklist

- [ ] Implement `ContainerRuntime` class
- [ ] Add detection for container/docker/podman
- [ ] Add platform-specific install instructions
- [ ] Create Dockerfile for agent image
- [ ] Set up GitHub Actions to build multi-platform images
- [ ] Add `--container` flag to `dispatch` command
- [ ] Add `--dangerous` flag (requires --container)
- [ ] Document security model
- [ ] Test on macOS (with and without Apple Container)
- [ ] Test on Linux (Docker and Podman)
- [ ] Test on Windows (Docker Desktop)
