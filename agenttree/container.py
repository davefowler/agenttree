"""Container runtime support for AgentTree."""

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


# =============================================================================
# Low-level Container Command Helpers (DRY wrappers for runtime differences)
# =============================================================================
# These take explicit runtime string for use in functions that don't have
# a ContainerRuntime instance. For high-level API, use stop_container(),
# delete_container() etc. defined later in this file.


def _get_delete_cmd(runtime: str) -> str:
    """Get the delete/remove command for the given runtime.
    
    Docker/Podman use 'rm', Apple Container uses 'delete'.
    """
    return "rm" if runtime in ("docker", "podman") else "delete"


def _run_stop(runtime: str, container_name: str, timeout: int = 5) -> bool:
    """Stop a container (low-level, takes runtime string).
    
    Args:
        runtime: Container runtime command (docker, container, podman)
        container_name: Name of the container to stop
        timeout: Timeout in seconds
        
    Returns:
        True if stopped successfully or already stopped, False on error
    """
    result = subprocess.run(
        [runtime, "stop", container_name],
        capture_output=True,
        timeout=timeout,
    )
    return result.returncode == 0


def _run_delete(runtime: str, container_name: str, timeout: int = 5) -> bool:
    """Delete/remove a container (low-level, takes runtime string).
    
    Args:
        runtime: Container runtime command (docker, container, podman)
        container_name: Name of the container to delete
        timeout: Timeout in seconds
        
    Returns:
        True if deleted successfully or didn't exist, False on error
    """
    delete_cmd = _get_delete_cmd(runtime)
    result = subprocess.run(
        [runtime, delete_cmd, container_name],
        capture_output=True,
        timeout=timeout,
    )
    return result.returncode == 0


def cleanup_container(runtime: str, container_name: str) -> None:
    """Stop and delete a container, waiting until it's actually gone.
    
    Use this when you need to ensure a container is gone before starting a new one.
    Takes runtime string for use in standalone functions.
    
    For Apple Container: stop can hang for minutes and the mDNS hostname lingers
    after delete. We use short stop timeout, then delete, then verify + wait.
    """
    import time

    if runtime == "container":
        # Apple Container: stop is very slow (can hang for minutes).
        # Use a short timeout — if it doesn't stop quickly, delete will handle it.
        try:
            _run_stop(runtime, container_name, timeout=15)
        except subprocess.TimeoutExpired:
            pass
        # Try delete (works even if stop timed out for stopped containers)
        try:
            _run_delete(runtime, container_name, timeout=60)
        except subprocess.TimeoutExpired:
            pass
        # Verify container is gone, then wait for mDNS hostname to de-register
        for _ in range(15):
            result = subprocess.run(
                [runtime, "inspect", container_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            # inspect returns [] for deleted containers, non-zero for unknown
            stdout = result.stdout.strip()
            if result.returncode != 0 or stdout == "[]":
                time.sleep(5)
                return
            time.sleep(2)
    else:
        # Docker/Podman: fast and reliable
        try:
            _run_stop(runtime, container_name, timeout=10)
        except subprocess.TimeoutExpired:
            pass
        try:
            _run_delete(runtime, container_name, timeout=10)
        except subprocess.TimeoutExpired:
            pass


def cleanup_containers_by_prefix(runtime: str, prefix: str) -> int:
    """Stop and delete all containers whose name starts with prefix.

    Used to clean up old timestamp-suffixed containers before starting a new one.
    Avoids the leak where each restart creates a new container but never cleans up
    the previous one.

    Args:
        runtime: Container runtime command
        prefix: Container name prefix to match (e.g., "agenttree-agenttree-042")

    Returns:
        Number of containers cleaned up
    """
    import json

    try:
        if runtime == "container":
            result = subprocess.run(
                ["container", "list", "--format", "json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return 0
            containers = json.loads(result.stdout) if result.stdout.strip() else []
            matching = [
                c.get("name", "") for c in containers
                if c.get("name", "").startswith(prefix)
            ]
        else:
            result = subprocess.run(
                [runtime, "ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=10,
            )
            matching = [n.strip() for n in result.stdout.splitlines() if n.strip()]

        cleaned = 0
        for name in matching:
            _run_stop(runtime, name, timeout=10)
            _run_delete(runtime, name, timeout=10)
            cleaned += 1
        return cleaned

    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError):
        return 0


def is_container_running(container_name: str) -> bool:
    """Check if a container with the given name is currently running.

    Args:
        container_name: Container name to check

    Returns:
        True if a running container with that name exists
    """
    import json

    runtime = get_container_runtime()
    if not runtime.runtime:
        return False

    try:
        if runtime.runtime == "container":
            result = subprocess.run(
                ["container", "inspect", container_name],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return False
            data = json.loads(result.stdout) if result.stdout.strip() else []
            return any(c.get("status") == "running" for c in data)
        else:
            result = subprocess.run(
                [runtime.runtime, "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True, text=True, timeout=10,
            )
            return result.returncode == 0 and "true" in result.stdout.lower()
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError):
        return False


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
        role: str = "developer",
        port: Optional[int] = None,
        container_name: Optional[str] = None,
        force_api_key: bool = False,
        share_git: bool = False,
    ) -> List[str]:
        """Build the container run command.

        Args:
            worktree_path: Path to the worktree to mount
            ai_tool: AI tool to run
            dangerous: Whether to run in dangerous mode (skip permissions)
            image: Container image to use
            additional_args: Additional arguments for the container
            agent_num: Agent number for container naming (deprecated, use container_name)
            model: Model to use (e.g., "opus", "sonnet"). Defaults to CLI default.
            role: Agent role (e.g., "developer", "reviewer"). Defaults to "developer".
            port: Dev server port to expose (e.g., 9001). If provided, adds -p port:port mapping.
            container_name: Explicit container name (e.g., "agenttree-issue-123-developer")
            force_api_key: Force API key mode (skip OAuth subscription)
            share_git: Mount git/gh credentials into container (~/.ssh, ~/.gitconfig, ~/.config/gh)

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

        # Name container for easier cleanup and tracking
        # Prefer explicit container_name, fall back to agent_num-based name
        if container_name:
            cmd.extend(["--name", container_name])
        elif agent_num is not None:
            cmd.extend(["--name", f"agenttree-agent-{agent_num}"])

        # Expose dev server port if configured
        if port is not None:
            cmd.extend(["-p", f"{port}:{port}"])

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
        # Each role gets its own session directory to keep conversations separate
        # This allows using `claude -c` to continue previous conversations
        # and prevents reviewer from continuing developer's session
        sessions_dir = abs_path / f".claude-sessions-{role}"
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
        # Skip OAuth when force_api_key is True to use API key instead
        if not force_api_key:
            oauth_token = get_credential("CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
            if oauth_token:
                cmd.extend(["-e", f"CLAUDE_CODE_OAUTH_TOKEN={oauth_token}"])

        # Always pass API key into container if available (for rate limit fallback)
        # This allows switching to API key mode without restarting container
        api_key = get_credential("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY")
        if api_key:
            cmd.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])

        # Set container indicator env var for reliable container detection
        cmd.extend(["-e", "AGENTTREE_CONTAINER=1"])

        # Set agent role for permission checking
        cmd.extend(["-e", f"AGENTTREE_ROLE={role}"])

        # Share git/gh credentials for push/PR access inside the container
        if share_git:
            ssh_dir = home / ".ssh"
            gitconfig = home / ".gitconfig"
            gh_config = home / ".config" / "gh"
            if ssh_dir.exists():
                cmd.extend(["-v", f"{ssh_dir}:/home/agent/.ssh:ro"])
            if gitconfig.exists():
                cmd.extend(["-v", f"{gitconfig}:/home/agent/.gitconfig:ro"])
            if gh_config.exists():
                cmd.extend(["-v", f"{gh_config}:/home/agent/.config/gh:ro"])
            # Pass GitHub token env vars if set
            for var in ("GITHUB_TOKEN", "GH_TOKEN"):
                if os.environ.get(var):
                    cmd.extend(["-e", f"{var}={os.environ[var]}"])

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

    def stop(self, container_id: str, timeout: int = 180) -> bool:
        """Stop a container by name or ID.

        Args:
            container_id: Container name or ID
            timeout: Timeout in seconds (Apple Containers can be slow)

        Returns:
            True if stopped successfully
        """
        if not self.runtime:
            return False
        try:
            result = subprocess.run(
                [self.runtime, "stop", container_id],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def delete(self, container_id: str, timeout: int = 180) -> bool:
        """Delete a container by name or ID.

        Args:
            container_id: Container name or ID
            timeout: Timeout in seconds (Apple Containers can be slow)

        Returns:
            True if deleted successfully
        """
        if not self.runtime:
            return False
        try:
            return _run_delete(self.runtime, container_id, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def list_all(self, filter_prefix: str | None = None) -> list[dict]:
        """List all containers with optional name filter.

        Args:
            filter_prefix: Optional prefix to filter container names/IDs

        Returns:
            List of container info dicts with keys: id, name, status, image
        """
        if not self.runtime:
            return []

        try:
            import json

            if self.runtime == "container":
                # Apple Container
                result = subprocess.run(
                    ["container", "list", "--format", "json"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    return []

                raw = json.loads(result.stdout) if result.stdout.strip() else []
                containers = []
                for c in raw:
                    config = c.get("configuration", {})
                    container_id = config.get("id", "")
                    image_info = config.get("image", {})
                    image = image_info.get("reference", "") if isinstance(image_info, dict) else ""
                    
                    if filter_prefix and not container_id.startswith(filter_prefix):
                        continue
                    
                    containers.append({
                        "id": container_id,
                        "name": container_id,  # Apple Container uses id as name
                        "status": c.get("status", "unknown"),
                        "image": image,
                    })
                return containers
            else:
                # Docker/Podman
                cmd = [self.runtime, "ps", "-a", "--format", "json"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                if result.returncode != 0:
                    return []

                containers = []
                # Docker outputs one JSON object per line
                for line in result.stdout.strip().splitlines():
                    if not line:
                        continue
                    c = json.loads(line)
                    name = c.get("Names", "")
                    
                    if filter_prefix and not name.startswith(filter_prefix):
                        continue
                    
                    containers.append({
                        "id": c.get("ID", ""),
                        "name": name,
                        "status": c.get("State", "unknown"),
                        "image": c.get("Image", ""),
                    })
                return containers

        except Exception:
            return []

    def cleanup_by_prefix(self, prefix: str, quiet: bool = False) -> int:
        """Stop and delete all containers matching a name prefix.

        Args:
            prefix: Container name prefix to match (e.g., "agenttree-myproject-")
            quiet: Suppress output if True

        Returns:
            Number of containers removed
        """
        if not self.runtime:
            return 0

        containers = self.list_all()
        removed = 0

        for c in containers:
            name = c.get("name", "") or c.get("id", "")
            image = c.get("image", "")
            
            # Match by prefix or by agenttree in image name
            if name.startswith(prefix) or (prefix.startswith("agenttree") and "agenttree" in image):
                self.stop(name)
                if self.delete(name):
                    removed += 1
                    if not quiet:
                        print(f"Removed: {name}")

        return removed


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
    return runtime.stop(container_id)


def delete_container(container_id: str) -> bool:
    """Delete a container by its name or ID.

    Args:
        container_id: Container name or ID

    Returns:
        True if deleted successfully, False otherwise
    """
    runtime = get_container_runtime()
    return runtime.delete(container_id)


def list_running_containers() -> list[str]:
    """List all running agenttree containers.

    Returns:
        List of container IDs for running agenttree containers
    """
    runtime = get_container_runtime()
    if not runtime.runtime:
        return []

    try:
        import json

        if runtime.runtime == "container":
            # Apple Container
            result = subprocess.run(
                ["container", "list", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []

            containers = json.loads(result.stdout) if result.stdout.strip() else []
            running = []
            for c in containers:
                if c.get("status") == "running":
                    container_id = c.get("id")
                    if container_id:
                        running.append(container_id)
            return running
        else:
            # Docker/Podman - filter by name pattern
            result = subprocess.run(
                [runtime.runtime, "ps", "-q", "--filter", "name=agenttree-agent"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []
            return [c.strip() for c in result.stdout.splitlines() if c.strip()]

    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def get_api_key_suffix(api_key: str) -> str:
    """Extract the suffix of an API key for Claude's approval system.
    
    Claude stores the last 20 characters of the API key.
    
    Args:
        api_key: Full API key
        
    Returns:
        The suffix portion used for approval tracking
    """
    return api_key[-20:]


def preapprove_api_key_in_container(
    runtime: str,
    container_name: str,
    api_key: str,
) -> bool:
    """Pre-approve an API key in the container's Claude config.
    
    Claude Code prompts to confirm API key usage on first run.
    By pre-populating the approval in ~/.claude.json, we skip this prompt.
    
    Args:
        runtime: Container runtime command (docker, container, podman)
        container_name: Name of the running container
        api_key: The API key to approve
        
    Returns:
        True if successful
    """
    key_suffix = get_api_key_suffix(api_key)
    
    # Python script to update or create the config
    python_script = f'''
import json
import os

config_path = os.path.expanduser("~/.claude.json")
config = {{"customApiKeyResponses": {{"approved": [], "rejected": []}}, "bypassPermissionsModeAccepted": True, "hasCompletedOnboarding": True}}

if os.path.exists(config_path):
    try:
        with open(config_path) as f:
            config = json.load(f)
    except:
        pass

# Ensure the structure exists
if "customApiKeyResponses" not in config:
    config["customApiKeyResponses"] = {{"approved": [], "rejected": []}}
if "approved" not in config["customApiKeyResponses"]:
    config["customApiKeyResponses"]["approved"] = []
if "rejected" not in config["customApiKeyResponses"]:
    config["customApiKeyResponses"]["rejected"] = []

# Add key to approved list, remove from rejected if present
key_suffix = "{key_suffix}"
if key_suffix not in config["customApiKeyResponses"]["approved"]:
    config["customApiKeyResponses"]["approved"].append(key_suffix)
if key_suffix in config["customApiKeyResponses"]["rejected"]:
    config["customApiKeyResponses"]["rejected"].remove(key_suffix)

# Pre-accept bypass permissions mode
config["bypassPermissionsModeAccepted"] = True
config["hasCompletedOnboarding"] = True

with open(config_path, "w") as f:
    json.dump(config, f, indent=2)
print("OK")
'''
    
    try:
        result = subprocess.run(
            [runtime, "exec", container_name, "python3", "-c", python_script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode == 0 and "OK" in result.stdout
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def start_container_detached(
    runtime: str,
    container_name: str,
    worktree_path: Path,
    image: str = "agenttree-agent:latest",
    port: int | None = None,
    api_key: str | None = None,
) -> bool:
    """Start a container in detached mode (not running claude yet).
    
    This allows us to configure the container before starting Claude.
    
    Args:
        runtime: Container runtime command
        container_name: Name for the container
        worktree_path: Path to mount as /workspace
        image: Container image
        port: Optional port to expose
        api_key: Optional API key to pass as env var
        
    Returns:
        True if container started successfully
    """
    # Clean up any existing container with this name
    cleanup_container(runtime, container_name)
    
    home = Path.home()
    abs_path = worktree_path.resolve()
    
    cmd = [
        runtime,
        "run",
        "-d",  # Detached mode
        "--name", container_name,
        "-v", f"{abs_path}:/workspace",
        "-w", "/workspace",
    ]
    
    # Mount git directories for worktrees
    main_git_dir, worktree_git_dir = get_git_worktree_info(abs_path)
    if main_git_dir and main_git_dir.exists():
        cmd.extend(["-v", f"{main_git_dir}:{main_git_dir}"])
        main_repo_dir = main_git_dir.parent
        agenttrees_dir = main_repo_dir / "_agenttree"
        if agenttrees_dir.exists():
            cmd.extend(["-v", f"{agenttrees_dir}:/workspace/_agenttree"])
    
    # Mount claude config directory
    claude_config_dir = home / ".claude"
    if claude_config_dir.exists():
        cmd.extend(["-v", f"{claude_config_dir}:/home/agent/.claude-host:ro"])
    
    # Expose port if specified
    if port:
        cmd.extend(["-p", f"{port}:{port}"])
    
    # Pass API key
    if api_key:
        cmd.extend(["-e", f"ANTHROPIC_API_KEY={api_key}"])
    
    # Container indicator env vars
    cmd.extend(["-e", "AGENTTREE_CONTAINER=1"])
    
    cmd.append(image)
    cmd.append("sleep")
    cmd.append("infinity")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return False
        
        # Wait for container to be ready (can accept exec commands)
        import time
        for _ in range(60):  # Wait up to 60 seconds
            check = subprocess.run(
                [runtime, "exec", container_name, "echo", "ready"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if check.returncode == 0:
                return True
            time.sleep(1)
        return False
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return False


def build_container_exec_claude_command(
    runtime: str,
    container_name: str,
    model: str,
    dangerous: bool = True,
) -> str:
    """Build the command to exec claude inside a running container.
    
    Args:
        runtime: Container runtime command  
        container_name: Name of the running container
        model: Model to use
        dangerous: Whether to skip permission prompts
        
    Returns:
        Command string for running in tmux
    """
    cmd_parts = [runtime, "exec", "-it", container_name, "claude"]
    
    if model:
        cmd_parts.extend(["--model", model])
    
    if dangerous:
        cmd_parts.append("--dangerously-skip-permissions")
    
    return " ".join(cmd_parts)
