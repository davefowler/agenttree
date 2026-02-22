"""Container runtime support for AgentTree."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agenttree.config import ContainerTypeConfig, ToolConfig


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


def build_container_command(
    runtime: str,
    worktree_path: Path,
    container_type: ContainerTypeConfig,
    container_name: str,
    tool_config: ToolConfig,
    role: str,
    issue_id: int | None = None,
    ports: list[int] | None = None,
    model: str | None = None,
    force_api_key: bool = False,
    interactive: bool = True,
) -> list[str]:
    """Build a generic container run command.

    This function has ZERO type-specific conditionals. All behavior differences
    come from the ContainerTypeConfig. There is no "if manager" or "if issue" -
    just config-driven command building.

    Layering order:
    1. Implicit system mounts (worktree, .git, _agenttree)
    2. Tool mounts (Claude config, session storage)
    3. User mounts (from container_type.mounts)
    4. System env vars (AGENTTREE_CONTAINER, AGENTTREE_ROLE, etc.)
    5. Tool env vars (auth tokens, API keys)
    6. User env vars (from container_type.env)
    7. Port forwarding (from collected session ports)
    8. Image and entry command

    Args:
        runtime: Container runtime command (docker, container, podman)
        worktree_path: Path to mount as /workspace
        container_type: Resolved ContainerTypeConfig (extends already resolved)
        container_name: Name for the container
        tool_config: Tool config for mounts/env/entry command
        role: Agent role (developer, reviewer, manager, etc.)
        issue_id: Issue ID if applicable (None for sandboxes/manager)
        ports: List of ports to forward
        model: Model for the AI tool
        force_api_key: Force API key mode (skip OAuth)
        interactive: Whether to use -it flags

    Returns:
        Complete container command as list of strings
    """
    from agenttree.config import render_template

    abs_path = worktree_path.resolve()
    home = Path.home()

    cmd = [runtime, "run"]

    if interactive:
        cmd.append("-it")

    # Container name
    cmd.extend(["--name", container_name])

    # === 1. Implicit system mounts (always present) ===

    # Mount worktree as /workspace
    cmd.extend(["-v", f"{abs_path}:/workspace"])
    cmd.extend(["-w", "/workspace"])

    # Mount git directory for worktrees so git operations work
    main_git_dir, _ = get_git_worktree_info(abs_path)
    if main_git_dir and main_git_dir.exists():
        cmd.extend(["-v", f"{main_git_dir}:{main_git_dir}"])

        # Mount _agenttree directory
        main_repo_dir = main_git_dir.parent
        agenttrees_dir = main_repo_dir / "_agenttree"
        if agenttrees_dir.exists():
            cmd.extend(["-v", f"{agenttrees_dir}:/workspace/_agenttree"])

    # === 2. Tool mounts ===
    for host_path, container_path, mode in tool_config.container_mounts(abs_path, role, home):
        mount_str = f"{host_path}:{container_path}"
        if mode and mode != "rw":
            mount_str += f":{mode}"
        cmd.extend(["-v", mount_str])

    # === 3. User mounts (from container_type config) ===
    for mount in container_type.mounts:
        # Expand ~ in mount paths
        if mount.startswith("~"):
            parts = mount.split(":", 2)
            parts[0] = str(Path(parts[0]).expanduser())
            mount = ":".join(parts)
        cmd.extend(["-v", mount])

    # === 4. System env vars ===
    cmd.extend(["-e", "AGENTTREE_CONTAINER=1"])
    cmd.extend(["-e", f"AGENTTREE_ROLE={role}"])

    if issue_id is not None:
        cmd.extend(["-e", f"AGENTTREE_ISSUE_ID={issue_id}"])

    # Set PORT env var if ports are configured
    if ports:
        cmd.extend(["-e", f"PORT={ports[0]}"])

    # === 5. Tool env vars ===
    for key, value in tool_config.container_env(home, force_api_key).items():
        cmd.extend(["-e", f"{key}={value}"])

    # === 6. User env vars (from container_type config) ===
    # Build context for Jinja rendering
    context: dict[str, object] = {
        "role": role,
        "port": ports[0] if ports else 9000,
    }
    if issue_id is not None:
        context["issue_id"] = issue_id

    for key, value in container_type.env.items():
        # Render Jinja templates in env values
        rendered_value = render_template(str(value), context)
        cmd.extend(["-e", f"{key}={rendered_value}"])

    # === 7. Port forwarding ===
    if ports:
        for port in ports:
            cmd.extend(["-p", f"{port}:{port}"])

    # === 8. Image ===
    image = container_type.image or "agenttree-agent:latest"
    cmd.append(image)

    # === 9. Entry command (from tool config) ===
    # Check if there's a prior session to continue
    sessions_dir = abs_path / f".claude-sessions-{role}"
    has_prior_session = sessions_dir.exists() and any(sessions_dir.glob("*.jsonl"))

    # Determine if dangerous mode is allowed
    # Both container type and role must allow it (we assume role allows since
    # that check happens at a higher level)
    # Default to True if None (matches pre-Optional behavior)
    dangerous = container_type.allow_dangerous if container_type.allow_dangerous is not None else True

    entry_cmd = tool_config.container_entry_command(
        model=model,
        dangerous=dangerous,
        continue_session=has_prior_session,
    )
    cmd.extend(entry_cmd)

    return cmd


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
