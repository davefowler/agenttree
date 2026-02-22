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


def session_name(
    project: str,
    session_type: str,
    issue_id: int,
    template: str = "{project}-{session_name}-{issue_id}",
) -> str:
    """Generate a tmux session name from a template.

    This is the ONE place that generates session names. All naming is
    template-based, allowing users to override the format.

    Args:
        project: Project name from config
        session_type: Session type (role name like "developer" or session
                      name like "serve")
        issue_id: Integer issue ID
        template: Name template with placeholders:
                  - {project}: project name
                  - {session_name}: session type
                  - {issue_id}: formatted issue ID

    Returns:
        Session name (e.g., "myproject-developer-042")

    Examples:
        >>> session_name("myapp", "developer", 42)
        'myapp-developer-042'
        >>> session_name("myapp", "serve", 42)
        'myapp-serve-042'
        >>> session_name("myapp", "manager", 0)
        'myapp-manager-000'
    """
    return template.format(
        project=project,
        session_name=session_type,
        issue_id=format_issue_id(issue_id),
    )


def tmux_session_name(project: str, issue_id: int, role: str = "developer") -> str:
    """Get tmux session name for an issue-bound agent.

    Args:
        project: Project name from config
        issue_id: Integer issue ID
        role: Agent role (default: "developer")

    Returns:
        Session name (e.g., "myproject-developer-042")
    """
    return session_name(project, role, issue_id)


def manager_session_name(project: str) -> str:
    """Get tmux session name for the manager agent.

    Args:
        project: Project name from config

    Returns:
        Session name (e.g., "myproject-manager-000")
    """
    return session_name(project, "manager", 0)


def serve_session_name(project: str, issue_id: int) -> str:
    """Get tmux session name for an issue's serve session.

    Args:
        project: Project name from config
        issue_id: Integer issue ID

    Returns:
        Session name (e.g., "myproject-serve-042")
    """
    return session_name(project, "serve", issue_id)


def container_type_session_name(
    project: str,
    container_type: str,
    name: str,
) -> str:
    """Get tmux session name for a user-defined container type.

    Used for containers created via `agenttree new {type} {name}`.

    Args:
        project: Project name from config
        container_type: Container type (e.g., "sandbox", "reviewer")
        name: Instance name (e.g., "my-sandbox")

    Returns:
        Session name (e.g., "myproject-sandbox-my-sandbox")
    """
    return f"{project}-{container_type}-{name}"


def worktree_dir_name(issue_id: int) -> str:
    """Get worktree directory name for an issue.

    Args:
        issue_id: Integer issue ID

    Returns:
        Worktree directory name (e.g., "issue-042")
    """
    return f"issue-{format_issue_id(issue_id)}"
