"""Git worktree management for AgentTree."""

import subprocess
from datetime import datetime
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
    current_task: Optional[str] = None
    task_count: int = 0


def get_tasks_dir(worktree_path: Path) -> Path:
    """Get the tasks directory for a worktree."""
    return worktree_path / "tasks"


def get_pending_tasks(worktree_path: Path) -> List[Path]:
    """Get all pending task files (not in archive), sorted oldest first.
    
    Args:
        worktree_path: Path to the worktree
        
    Returns:
        List of task file paths, sorted by creation time (oldest first)
    """
    tasks_dir = get_tasks_dir(worktree_path)
    if not tasks_dir.exists():
        return []
    
    # Get all .md files in tasks/ (not in archive/)
    task_files = [f for f in tasks_dir.glob("*.md") if f.is_file()]
    
    # Sort by file modification time (oldest first = FIFO)
    return sorted(task_files, key=lambda f: f.stat().st_mtime)


def get_current_task(worktree_path: Path) -> Optional[Path]:
    """Get the current (oldest) task to work on.
    
    Args:
        worktree_path: Path to the worktree
        
    Returns:
        Path to the oldest task file, or None if no tasks
    """
    tasks = get_pending_tasks(worktree_path)
    return tasks[0] if tasks else None


def get_task_title(task_path: Path) -> str:
    """Extract title from a task file.
    
    Args:
        task_path: Path to the task file
        
    Returns:
        Task title (from first # heading or filename)
    """
    try:
        content = task_path.read_text()
        for line in content.split("\n"):
            if line.startswith("# "):
                # Remove "# " and "Task: " prefix if present
                title = line[2:].strip()
                if title.lower().startswith("task:"):
                    title = title[5:].strip()
                return title
    except Exception:
        pass
    
    # Fallback to filename without date prefix and extension
    name = task_path.stem
    # Remove date prefix like "2026-01-01-"
    if len(name) > 11 and name[10] == "-":
        name = name[11:]
    return name.replace("-", " ").title()


def has_pending_tasks(worktree_path: Path) -> bool:
    """Check if there are any pending tasks.
    
    Args:
        worktree_path: Path to the worktree
        
    Returns:
        True if there are pending tasks
    """
    return len(get_pending_tasks(worktree_path)) > 0


def is_busy(worktree_path: Path) -> bool:
    """Check if an agent is busy.

    An agent is busy if:
    - It has pending tasks in tasks/ folder, OR
    - It has uncommitted git changes

    Args:
        worktree_path: Path to the worktree

    Returns:
        True if agent is busy
    """
    # Check for pending tasks
    if has_pending_tasks(worktree_path):
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


def archive_task(task_path: Path) -> Path:
    """Move a completed task to the archive.
    
    Args:
        task_path: Path to the task file
        
    Returns:
        Path to the archived task file
    """
    archive_dir = task_path.parent / "archive"
    archive_dir.mkdir(exist_ok=True)
    
    archived_path = archive_dir / task_path.name
    task_path.rename(archived_path)
    return archived_path


def create_task_file(
    worktree_path: Path,
    title: str,
    content: str,
    issue_number: Optional[int] = None
) -> Path:
    """Create a new task file with dated filename.
    
    Args:
        worktree_path: Path to the worktree
        title: Task title
        content: Full task content (markdown)
        issue_number: Optional GitHub issue number
        
    Returns:
        Path to the created task file
    """
    tasks_dir = get_tasks_dir(worktree_path)
    tasks_dir.mkdir(exist_ok=True)
    
    # Create filename: YYYY-MM-DD-slug.md
    date_str = datetime.now().strftime("%Y-%m-%d")
    
    # Create slug from title
    slug = title.lower()
    slug = "".join(c if c.isalnum() or c == " " else "" for c in slug)
    slug = "-".join(slug.split())[:50]  # Max 50 chars
    
    if issue_number:
        filename = f"{date_str}-issue-{issue_number}-{slug}.md"
    else:
        filename = f"{date_str}-{slug}.md"
    
    task_path = tasks_dir / filename
    task_path.write_text(content)
    
    return task_path


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


def update_worktree_with_main(worktree_path: Path, base_branch: str = "main") -> bool:
    """Update worktree to include latest main while preserving agent's work.

    This is used when restarting an agent to ensure they have the latest
    agenttree CLI code while keeping their implementation work.

    Args:
        worktree_path: Path to the worktree
        base_branch: Name of the base branch (default: "main")

    Returns:
        True if update succeeded, False if there are conflicts to resolve
    """
    # 1. Commit any uncommitted work
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        subprocess.run(["git", "add", "-A"], cwd=worktree_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "WIP: uncommitted work before restart"],
            cwd=worktree_path,
            check=True,
        )

    # 2. Fetch latest from origin
    subprocess.run(["git", "fetch", "origin"], cwd=worktree_path, check=True)

    # 3. Pull latest of this branch (in case of remote changes)
    subprocess.run(
        ["git", "pull", "--rebase", "--autostash"],
        cwd=worktree_path,
        capture_output=True,  # Don't fail if no upstream
    )

    # 4. Try to rebase onto main (cleaner history)
    result = subprocess.run(
        ["git", "rebase", f"origin/{base_branch}"],
        cwd=worktree_path,
        capture_output=True,
    )
    if result.returncode == 0:
        return True

    # 5. Rebase failed - abort and try merge instead
    subprocess.run(
        ["git", "rebase", "--abort"],
        cwd=worktree_path,
        capture_output=True,
    )

    result = subprocess.run(
        ["git", "merge", f"origin/{base_branch}", "-m", "Merge main for latest tooling"],
        cwd=worktree_path,
        capture_output=True,
    )
    if result.returncode == 0:
        return True

    # 6. Merge also has conflicts - agent will need to resolve
    return False


def reset_worktree(worktree_path: Path, base_branch: str = "main") -> None:
    """Reset worktree to latest version of base branch (DESTRUCTIVE).

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

    # Get agent number from worktree path to create unique branch
    worktree_name = worktree_path.name
    work_branch = f"{worktree_name}-work"
    
    # Delete the work branch if it exists (so we can recreate it fresh)
    subprocess.run(
        ["git", "branch", "-D", work_branch],
        cwd=worktree_path,
        capture_output=True,  # Don't fail if branch doesn't exist
    )
    
    # Create fresh work branch from origin/main
    # Using -B to force-create (replaces if exists)
    subprocess.run(
        ["git", "checkout", "-B", work_branch, f"origin/{base_branch}"],
        cwd=worktree_path,
        check=True,
    )

    # Clean untracked files
    subprocess.run(
        ["git", "clean", "-fd"],
        cwd=worktree_path,
        check=True,
    )

    # Archive any pending tasks (they're being reset, not completed)
    for task_file in get_pending_tasks(worktree_path):
        archive_task(task_file)


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

        # Check for pending tasks
        pending_tasks = get_pending_tasks(worktree_path)
        has_task = len(pending_tasks) > 0
        task_count = len(pending_tasks)
        
        # Get current task title
        current_task_title = None
        if pending_tasks:
            current_task_title = get_task_title(pending_tasks[0])

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

        # Agent is busy if it has tasks or uncommitted changes
        busy = has_task or has_uncommitted

        return WorktreeStatus(
            agent_num=agent_num,
            path=worktree_path,
            branch=branch,
            has_task=has_task,
            has_uncommitted=has_uncommitted,
            is_busy=busy,
            current_task=current_task_title,
            task_count=task_count,
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
