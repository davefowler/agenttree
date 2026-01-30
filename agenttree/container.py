"""Container runtime support for AgentTree."""

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


def get_git_worktree_info(worktree_path: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """Get git directory info for a worktree.

    Git worktrees have a .git FILE (not directory) that points to the main
    repo's .git directory. We need to mount that directory in the container
    for git operations to work.

    Args:
        worktree_path: Path to the worktree

    Returns:
        Tuple of (main_git_dir, worktree_git_dir) or (None, None) if not a worktree
    """
    git_path = worktree_path / ".git"

    if not git_path.exists():
        return None, None

    # If .git is a directory, this is a regular repo, not a worktree
    if git_path.is_dir():
        return None, None

    # .git is a file - read it to get the gitdir path
    try:
        content = git_path.read_text().strip()
        # Format: "gitdir: /path/to/.git/worktrees/name"
        match = re.match(r'^gitdir:\s*(.+)$', content)
        if match:
            worktree_git_dir = Path(match.group(1))
            # The main .git dir is the parent of "worktrees"
            # e.g., /repo/.git/worktrees/agent-1 -> /repo/.git
            if "worktrees" in worktree_git_dir.parts:
                idx = worktree_git_dir.parts.index("worktrees")
                main_git_dir = Path(*worktree_git_dir.parts[:idx])
                return main_git_dir, worktree_git_dir
    except Exception:
        pass

    return None, None


class ContainerRuntime:
    """Container runtime manager."""

    def __init__(self) -> None:
        """Initialize container runtime."""
        self.runtime = self.detect_runtime()

    @staticmethod
    def detect_runtime() -> Optional[str]:
        """Detect available container runtime.

        Returns:
            Runtime name ("container", "docker", "podman") or None
        """
        system = platform.system()

        if system == "Darwin":  # macOS
            if shutil.which("container"):  # Apple Container (macOS 26+)
                return "container"
            elif shutil.which("docker"):
                return "docker"
        elif system == "Linux":
            if shutil.which("docker"):
                return "docker"
            elif shutil.which("podman"):
                return "podman"
        elif system == "Windows":
            if shutil.which("docker"):
                return "docker"

        return None

    def is_available(self) -> bool:
        """Check if a container runtime is available.

        Returns:
            True if runtime is available
        """
        return self.runtime is not None

    def ensure_system_running(self) -> bool:
        """Ensure the container system service is running.

        For Apple Container, the system service must be started before running containers.
        For Docker, the Docker daemon must be running.

        Returns:
            True if system is running or was started successfully, False if failed
        """
        if self.runtime == "container":
            return self._ensure_apple_container_running()
        elif self.runtime == "docker":
            return self._ensure_docker_running()
        # Podman doesn't need a daemon
        return True

    def _ensure_apple_container_running(self) -> bool:
        """Ensure Apple Container system is running."""
        try:
            result = subprocess.run(
                ["container", "system", "status"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if "apiserver is running" in result.stdout:
                return True

            print("Starting Apple Container system service...")
            start_result = subprocess.run(
                ["container", "system", "start"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return start_result.returncode == 0
        except Exception as e:
            print(f"Warning: Could not check/start container system: {e}")
            return False

    def _ensure_docker_running(self) -> bool:
        """Ensure Docker daemon is running."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return True

            # Docker not running - try to start it on macOS
            system = platform.system()
            if system == "Darwin":
                print("Docker daemon not running. Attempting to start Docker Desktop...")
                subprocess.run(
                    ["open", "-a", "Docker"],
                    capture_output=True,
                    timeout=5,
                )
                # Wait for Docker to start (up to 30 seconds)
                import time
                for _ in range(30):
                    time.sleep(1)
                    check = subprocess.run(
                        ["docker", "info"],
                        capture_output=True,
                        timeout=5,
                    )
                    if check.returncode == 0:
                        return True
                print("Warning: Docker Desktop did not start in time")
                return False
            else:
                print("Warning: Docker daemon is not running. Please start Docker.")
                return False
        except Exception as e:
            print(f"Warning: Could not check Docker status: {e}")
            return False

    def build_run_command(
        self,
        worktree_path: Path,
        ai_tool: str = "claude",
        dangerous: bool = False,
        image: str = "agenttree-agent:latest",
        additional_args: Optional[List[str]] = None,
        agent_num: Optional[int] = None,
        model: Optional[str] = None,
        agent_host: str = "agent",
    ) -> List[str]:
        """Build the container run command.

        Args:
            worktree_path: Path to the worktree to mount
            ai_tool: AI tool to run
            dangerous: Whether to run in dangerous mode (skip permissions)
            image: Container image to use
            additional_args: Additional arguments for the container
            agent_num: Agent number for container naming
            model: Model to use (e.g., "opus", "sonnet"). Defaults to CLI default.
            agent_host: Agent host type (e.g., "agent", "review"). Defaults to "agent".

        Returns:
            Command list

        Raises:
            RuntimeError: If no container runtime available
        """
        if not self.runtime:
            raise RuntimeError(
                "No container runtime available. "
                "Install Docker or upgrade to macOS 26+ for Apple Container."
            )

        # Apple Container requires absolute paths for volume mounts
        abs_path = worktree_path.resolve()
        home = Path.home()

        cmd = [
            self.runtime,
            "run",
            "-it",
            "-v",
            f"{abs_path}:/workspace",
            "-w",
            "/workspace",
        ]

        # Name container for persistence (can restart without re-auth)
        if agent_num is not None:
            cmd.extend(["--name", f"agenttree-agent-{agent_num}"])

        # Mount git directory for worktrees so git operations work in container
        # Worktrees have a .git file pointing to /path/to/repo/.git/worktrees/name
        # We mount the main .git dir at the same path so the reference resolves
        main_git_dir, worktree_git_dir = get_git_worktree_info(abs_path)
        if main_git_dir and main_git_dir.exists():
            # Mount main .git directory at the same absolute path inside container
            cmd.extend(["-v", f"{main_git_dir}:{main_git_dir}"])

            # Also mount _agenttree directory so agent can access issue files and state
            # The _agenttree dir is in the main repo, not the worktree
            # Mount it at /workspace/_agenttree so it's accessible from the working directory
            main_repo_dir = main_git_dir.parent
            agenttrees_dir = main_repo_dir / "_agenttree"
            if agenttrees_dir.exists():
                cmd.extend(["-v", f"{agenttrees_dir}:/workspace/_agenttree"])

        # Mount ~/.claude directory (contains settings, but skip if it would cause issues)
        # Note: ~/.claude.json is the main config but Apple Container can't mount files, only dirs
        # The entrypoint copies ~/.claude.json from a mounted config dir if available
        claude_config_dir = home / ".claude"
        if claude_config_dir.exists():
            cmd.extend(["-v", f"{claude_config_dir}:/home/agent/.claude-host:ro"])

        # Mount session storage for conversation persistence across restarts
        # Each worktree gets its own session directory, mapped to Claude's project path
        # This allows using `claude -c` to continue previous conversations
        sessions_dir = abs_path / ".claude-sessions"
        sessions_dir.mkdir(exist_ok=True)
        cmd.extend(["-v", f"{sessions_dir}:/home/agent/.claude/projects/-workspace"])

        # Check if there are existing sessions to continue
        has_prior_session = any(sessions_dir.glob("*.jsonl"))

        # Pass through auth credentials
        # Helper to get credential from env or file
        def get_credential(env_var: str, file_key: str) -> Optional[str]:
            # Check environment first
            if os.environ.get(env_var):
                return os.environ[env_var]
            # Fall back to credentials file
            creds_file = home / ".config" / "agenttree" / "credentials"
            if creds_file.exists():
                for line in creds_file.read_text().splitlines():
                    if line.startswith(f"{file_key}="):
                        return line.split("=", 1)[1].strip()
            return None

        # OAuth token for subscription auth (from `claude setup-token`)
        oauth_token = get_credential("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
        if oauth_token:
            cmd.extend(["-e", f"CLAUDE_CODE_OAUTH_TOKEN={oauth_token}"])

        # Set container indicator env var for reliable container detection
        cmd.extend(["-e", "AGENTTREE_CONTAINER=1"])

        # Set agent host type for permission checking
        cmd.extend(["-e", f"AGENTTREE_AGENT_HOST={agent_host}"])

        if additional_args:
            cmd.extend(additional_args)

        cmd.append(image)
        cmd.append(ai_tool)

        # Use -c to continue previous session if one exists
        # Only add -c when there's a prior session (Claude exits if no session to continue)
        if has_prior_session:
            cmd.append("-c")

        if model:
            cmd.extend(["--model", model])

        if dangerous:
            cmd.append("--dangerously-skip-permissions")

        return cmd

    def run_in_container(
        self,
        worktree_path: Path,
        ai_tool: str = "claude",
        dangerous: bool = False,
        image: str = "agenttree-agent:latest",
        additional_args: Optional[List[str]] = None,
    ) -> subprocess.Popen:
        """Run AI tool in a container.

        Args:
            worktree_path: Path to the worktree
            ai_tool: AI tool to run
            dangerous: Whether to run in dangerous mode
            image: Container image to use
            additional_args: Additional container arguments

        Returns:
            Process handle

        Raises:
            RuntimeError: If no container runtime available
        """
        cmd = self.build_run_command(
            worktree_path, ai_tool, dangerous, image, additional_args
        )

        return subprocess.Popen(cmd)

    def get_runtime_name(self) -> str:
        """Get the name of the detected runtime.

        Returns:
            Runtime name or "none"
        """
        return self.runtime or "none"

    def get_recommended_action(self) -> str:
        """Get recommendation for installing a container runtime.

        Returns:
            Installation instructions
        """
        system = platform.system()

        if system == "Darwin":
            return "Upgrade to macOS 26+ for Apple Container (recommended)\nOr install Docker: brew install docker"
        elif system == "Linux":
            return "Install Docker: sudo apt install docker.io\nOr install Podman: sudo apt install podman"
        elif system == "Windows":
            return "Install Docker Desktop or use WSL2 with Docker"
        else:
            return "Install Docker or a compatible container runtime"


# Global container runtime instance
_runtime: Optional[ContainerRuntime] = None


def get_container_runtime() -> ContainerRuntime:
    """Get the global container runtime instance.

    Returns:
        ContainerRuntime instance
    """
    global _runtime
    if _runtime is None:
        _runtime = ContainerRuntime()
    return _runtime


def find_container_by_worktree(worktree_path: Path) -> Optional[str]:
    """Find a running container's UUID by its worktree mount path.

    Apple Containers use UUIDs, not names. This function inspects running
    containers to find one that has the given worktree mounted.

    Args:
        worktree_path: Path to the worktree (e.g., .worktrees/issue-045-...)

    Returns:
        Container UUID if found, None otherwise
    """
    runtime = get_container_runtime()
    if runtime.runtime != "container":
        # Docker/Podman use names, not UUIDs - return None to use name-based lookup
        return None

    try:
        import json

        # Get list of running containers
        result = subprocess.run(
            ["container", "list", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None

        containers = json.loads(result.stdout) if result.stdout.strip() else []

        # Normalize the worktree path for comparison
        abs_worktree = str(worktree_path.resolve())

        # Limit containers checked to avoid performance issues with many containers
        MAX_CONTAINERS_TO_CHECK = 50
        checked = 0

        for container in containers:
            if checked >= MAX_CONTAINERS_TO_CHECK:
                break

            if container.get("status") != "running":
                continue

            container_id: Optional[str] = container.get("id")
            if not container_id:
                continue

            checked += 1

            # Inspect container to get mount info
            inspect_result = subprocess.run(
                ["container", "inspect", container_id],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if inspect_result.returncode != 0:
                continue

            try:
                inspect_data = json.loads(inspect_result.stdout)
                if not inspect_data:
                    continue

                mounts = inspect_data[0].get("configuration", {}).get("mounts", [])
                for mount in mounts:
                    source = mount.get("source", "")
                    # Check if this mount matches our worktree
                    if source.rstrip("/") == abs_worktree.rstrip("/"):
                        return container_id
            except (json.JSONDecodeError, IndexError, KeyError):
                continue

        return None

    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError):
        # Expected errors when container runtime unavailable or returns bad data
        return None


def stop_container_by_id(container_id: str) -> bool:
    """Stop a container by its UUID.

    Args:
        container_id: Container UUID

    Returns:
        True if stopped successfully, False otherwise
    """
    runtime = get_container_runtime()
    if not runtime.runtime:
        return False

    try:
        result = subprocess.run(
            [runtime.runtime, "stop", container_id],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False
