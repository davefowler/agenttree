"""Issue ID formatting and parsing.

This module is the single source of truth for how issue IDs are formatted
for external use (directories, container names, session names, etc.).

All issue IDs are integers internally. This module handles:
- Parsing user input strings to int
- Formatting int IDs to padded strings for external names
- Generating consistent names for containers, sessions, directories
"""


def parse_issue_id(s: str) -> int:
    """Parse issue ID from user input.

    This is the ONE place that converts user input to int.
    Handles: "1", "01", "001", "1001", etc.

    Args:
        s: User-provided issue ID string

    Returns:
        Integer issue ID

    Raises:
        ValueError: If input cannot be parsed as an integer
    """
    if not s or not s.strip():
        raise ValueError(f"Invalid issue ID: {s!r}")
    stripped = s.lstrip("0") or "0"
    return int(stripped)


def format_issue_id(issue_id: int) -> str:
    """Format issue ID with 3-digit minimum padding.

    Examples:
        1 -> "001"
        42 -> "042"
        999 -> "999"
        1001 -> "1001"

    Args:
        issue_id: Integer issue ID

    Returns:
        Padded string representation
    """
    return f"{issue_id:03d}"



def container_name(project: str, issue_id: int) -> str:
    """Get container name for an issue-bound agent.

    Args:
        project: Project name from config
        issue_id: Integer issue ID

    Returns:
        Container name (e.g., "agenttree-myproject-042")
    """
    return f"agenttree-{project}-{format_issue_id(issue_id)}"


def tmux_session_name(project: str, issue_id: int, role: str = "developer") -> str:
    """Get tmux session name for an issue-bound agent.

    Args:
        project: Project name from config
        issue_id: Integer issue ID
        role: Agent role (default: "developer")

    Returns:
        Session name (e.g., "myproject-developer-042")
    """
    return f"{project}-{role}-{format_issue_id(issue_id)}"


def manager_session_name(project: str) -> str:
    """Get tmux session name for the manager agent.

    Args:
        project: Project name from config

    Returns:
        Session name (e.g., "myproject-manager-000")
    """
    return f"{project}-manager-000"


def worktree_dir_name(issue_id: int) -> str:
    """Get worktree directory name for an issue.

    Args:
        issue_id: Integer issue ID

    Returns:
        Worktree directory name (e.g., "issue-042")
    """
    return f"issue-{format_issue_id(issue_id)}"
