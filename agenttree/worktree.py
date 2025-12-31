"""Git worktree management for AgentTree."""

import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel

from agenttree.config import Config


class WorktreeStatus(BaseModel):
    """Status of an agent worktree."""

    agent_num: int
    path: Path
    branch: str
    has_task: bool
    has_uncommitted: bool
    is_busy: bool


def is_busy(worktree_path: Path) -> bool:
    """Check if an agent is busy.

    An agent is busy if:
    - It has a TASK.md file, OR
    - It has uncommitted git changes

    Args:
        worktree_path: Path to the worktree

    Returns:
        True if agent is busy
    """
    # Check for TASK.md
    if (worktree_path / "TASK.md").exists():
        return True

    # Check for uncommitted changes
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def create_worktree(
    repo_path: Path, worktree_path: Path, branch_name: str
) -> None:
    """Create a new git worktree.

    Args:
        repo_path: Path to the main repository
        worktree_path: Path where the worktree should be created
        branch_name: Name of the branch for this worktree
    """
    # Create branch (ignore error if it already exists)
    try:
        subprocess.run(
            ["git", "branch", branch_name, "HEAD"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        # Branch already exists, that's fine
        pass

    # Create worktree
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), branch_name],
        cwd=repo_path,
        check=True,
    )


def remove_worktree(repo_path: Path, worktree_path: Path) -> None:
    """Remove a git worktree.

    Args:
        repo_path: Path to the main repository
        worktree_path: Path to the worktree to remove
    """
    try:
        subprocess.run(
            ["git", "worktree", "remove", str(worktree_path)],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        # Worktree doesn't exist or already removed
        pass


def reset_worktree(worktree_path: Path, base_branch: str = "main") -> None:
    """Reset worktree to latest version of base branch.

    Args:
        worktree_path: Path to the worktree
        base_branch: Name of the base branch (default: "main")
    """
    # Fetch latest
    subprocess.run(
        ["git", "fetch", "origin"],
        cwd=worktree_path,
        check=True,
    )

    # Checkout base branch
    try:
        subprocess.run(
            ["git", "checkout", base_branch],
            cwd=worktree_path,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        # Branch doesn't exist locally, create it from origin
        subprocess.run(
            ["git", "checkout", "-b", base_branch, f"origin/{base_branch}"],
            cwd=worktree_path,
            check=True,
        )

    # Reset to origin
    subprocess.run(
        ["git", "reset", "--hard", f"origin/{base_branch}"],
        cwd=worktree_path,
        check=True,
    )

    # Clean untracked files
    subprocess.run(
        ["git", "clean", "-fd"],
        cwd=worktree_path,
        check=True,
    )

    # Remove TASK.md if it exists
    task_file = worktree_path / "TASK.md"
    if task_file.exists():
        task_file.unlink()


def list_worktrees(repo_path: Path) -> List[Dict[str, str]]:
    """List all git worktrees.

    Args:
        repo_path: Path to the main repository

    Returns:
        List of worktree information dictionaries
    """
    result = subprocess.run(
        ["git", "worktree", "list"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    worktrees = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue

        # Parse: /path/to/worktree  commit_hash [branch]
        parts = line.split()
        if len(parts) >= 3:
            path = parts[0]
            branch = parts[2].strip("[]")
            worktrees.append({"path": path, "branch": branch})

    return worktrees


class WorktreeManager:
    """Manages git worktrees for agents."""

    def __init__(self, repo_path: Path, config: Config):
        """Initialize the worktree manager.

        Args:
            repo_path: Path to the main git repository
            config: AgentTree configuration
        """
        self.repo_path = repo_path
        self.config = config

    def setup_agent(self, agent_num: int) -> Path:
        """Set up a worktree for an agent.

        Args:
            agent_num: Agent number

        Returns:
            Path to the created worktree
        """
        worktree_path = self.config.get_worktree_path(agent_num)
        branch_name = f"agent-{agent_num}-work"

        # Create worktree directory if needed
        worktree_path.parent.mkdir(parents=True, exist_ok=True)

        # Create worktree
        create_worktree(self.repo_path, worktree_path, branch_name)

        return worktree_path

    def dispatch(
        self, agent_num: int, base_branch: str = "main", force: bool = False
    ) -> None:
        """Dispatch an agent by resetting its worktree.

        Args:
            agent_num: Agent number
            base_branch: Base branch to reset to
            force: Force dispatch even if agent is busy

        Raises:
            RuntimeError: If agent is busy and force is False
        """
        worktree_path = self.config.get_worktree_path(agent_num)

        # Check if agent is busy
        if not force and is_busy(worktree_path):
            raise RuntimeError(
                f"Agent {agent_num} is busy. Use force=True to override."
            )

        # Reset worktree
        reset_worktree(worktree_path, base_branch)

    def get_status(self, agent_num: int) -> WorktreeStatus:
        """Get status of an agent.

        Args:
            agent_num: Agent number

        Returns:
            WorktreeStatus object
        """
        worktree_path = self.config.get_worktree_path(agent_num)

        # Get current branch
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
            )
            branch = result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            branch = "unknown"

        # Check for TASK.md
        has_task = (worktree_path / "TASK.md").exists()

        # Check for uncommitted changes
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=False,
            )
            has_uncommitted = bool(result.stdout.strip())
        except (subprocess.CalledProcessError, FileNotFoundError):
            has_uncommitted = False

        # Agent is busy if it has a task or uncommitted changes
        busy = has_task or has_uncommitted

        return WorktreeStatus(
            agent_num=agent_num,
            path=worktree_path,
            branch=branch,
            has_task=has_task,
            has_uncommitted=has_uncommitted,
            is_busy=busy,
        )

    def list_all(self) -> List[Dict[str, str]]:
        """List all worktrees.

        Returns:
            List of worktree information
        """
        return list_worktrees(self.repo_path)

    def cleanup(self, agent_num: int) -> None:
        """Clean up an agent's worktree.

        Args:
            agent_num: Agent number
        """
        worktree_path = self.config.get_worktree_path(agent_num)
        remove_worktree(self.repo_path, worktree_path)
