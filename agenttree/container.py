"""Container runtime support for AgentTree."""

import platform
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional


class ContainerRuntime:
    """Container runtime manager."""

    def __init__(self):
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

    def build_run_command(
        self,
        worktree_path: Path,
        ai_tool: str = "claude",
        dangerous: bool = False,
        image: str = "agenttree-agent:latest",
        additional_args: Optional[List[str]] = None,
        agent_num: Optional[int] = None,
    ) -> List[str]:
        """Build the container run command.

        Args:
            worktree_path: Path to the worktree to mount
            ai_tool: AI tool to run
            dangerous: Whether to run in dangerous mode (skip permissions)
            image: Container image to use
            additional_args: Additional arguments for the container

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
        claude_config = home / ".claude"

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

        # Mount Claude config for subscription auth (if exists)
        if claude_config.exists():
            cmd.extend(["-v", f"{claude_config}:/home/agent/.claude"])

        # Pass through auth credentials if set
        import os
        # API key for direct API access
        if os.environ.get("ANTHROPIC_API_KEY"):
            cmd.extend(["-e", f"ANTHROPIC_API_KEY={os.environ['ANTHROPIC_API_KEY']}"])
        # OAuth token for subscription auth (from `claude setup-token`)
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            cmd.extend(["-e", f"CLAUDE_CODE_OAUTH_TOKEN={os.environ['CLAUDE_CODE_OAUTH_TOKEN']}"])

        if additional_args:
            cmd.extend(additional_args)

        cmd.append(image)
        cmd.append(ai_tool)

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
