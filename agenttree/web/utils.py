"""Helper functions for web routes."""

import hashlib
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from agenttree import issues as issue_crud
from agenttree.config import load_config
from agenttree.web.agent_manager import agent_manager
from agenttree.web.models import KanbanBoard, Issue as WebIssue

# Load config at module level
_config = load_config()

# Pattern to match Claude Code's input prompt separator line
# The separator is a line of U+2500 (BOX DRAWINGS LIGHT HORIZONTAL) characters: ─
# We match lines that are at least 20 of these characters (with optional whitespace)
_PROMPT_SEPARATOR_PATTERN = re.compile(r"^\s*─{20,}\s*$")


def _strip_claude_input_prompt(output: str) -> str:
    """Strip Claude Code's input prompt area from tmux output.

    Claude Code displays a separator (a line of ─ characters) before its input
    prompt. We truncate at the first such separator to show only the conversation.
    """
    lines = output.split("\n")

    for i, line in enumerate(lines):
        if _PROMPT_SEPARATOR_PATTERN.match(line):
            # Found the separator - return everything before it
            return "\n".join(lines[:i]).rstrip()

    return output


def _compute_etag(content: str) -> str:
    """Compute an ETag header value from content.

    Returns a quoted MD5 hash of the content suitable for use as an ETag header.
    """
    content_hash = hashlib.md5(content.encode()).hexdigest()
    return f'"{content_hash}"'


def format_duration(minutes: int) -> str:
    """Format minutes as '0m', '2h', or '3d'."""
    if minutes < 60:
        return f"{minutes}m"
    elif minutes < 1440:  # Less than 24 hours
        hours = minutes // 60
        return f"{hours}h"
    else:
        days = minutes // 1440
        return f"{days}d"


# File ordering by workflow stage (problem first, then spec, etc.)
STAGE_FILE_ORDER = [
    "problem.md",
    "research.md",
    "spec.md",
    "spec_review.md",
    "review.md",
    "independent_review.md",
    "feedback.md",
]

# Mapping of filenames to their associated workflow dot path.
# Used to determine if a file's stage has been "passed" relative to the current stage.
FILE_TO_STAGE: dict[str, str] = {
    "problem.md": "explore.define",
    "research.md": "explore.research",
    "spec.md": "plan.draft",
    "spec_review.md": "plan.assess",
    "review.md": "implement.code_review",
    "independent_review.md": "implement.independent_review",
    "feedback.md": "implement.feedback",
}

# Maximum diff size in bytes (200KB - show more before truncating)
MAX_DIFF_SIZE = 200 * 1024


def convert_issue_to_web(
    issue: issue_crud.Issue, load_dependents: bool = False
) -> WebIssue:
    """Convert an issue_crud.Issue to a web Issue model.

    Args:
        issue: The issue to convert
        load_dependents: If True, also load dependent issues (issues blocked by this one)
    """
    # Check if tmux session is active for this issue.
    # For human review stages, check the developer agent (the review stage
    # itself has no agent — it's waiting for human action).
    if _config.is_human_review(issue.stage):
        from agenttree.ids import parse_issue_id

        iid = parse_issue_id(str(issue.id))
        dev_session = _config.get_issue_tmux_session(iid, "developer")
        tmux_active = dev_session in agent_manager._get_active_sessions()
    else:
        tmux_active = agent_manager._check_issue_tmux_session(issue.id)

    # Load dependents if requested (issues blocked by this one)
    dependents: list[int] = []
    if load_dependents:
        dependent_issues = issue_crud.get_dependent_issues(issue.id)
        dependents = [d.id for d in dependent_issues]

    # Calculate time in current stage from history
    time_in_stage = "0m"
    if issue.history:
        from datetime import timezone

        last_entry = issue.history[-1]
        try:
            # Handle both ISO format with and without timezone
            ts = last_entry.timestamp.replace("Z", "+00:00")
            stage_entered = datetime.fromisoformat(ts)
            # Make sure both are timezone-aware for comparison
            if stage_entered.tzinfo is None:
                stage_entered = stage_entered.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            minutes_elapsed = int((now - stage_entered).total_seconds() / 60)
            time_in_stage = format_duration(max(0, minutes_elapsed))
        except (ValueError, AttributeError):
            # Fall back to 0m if timestamp parsing fails
            pass

    return WebIssue(
        number=issue.id,
        title=issue.title,
        body="",  # Loaded separately from problem.md
        labels=issue.labels,
        assignees=[],
        stage=issue.stage,  # Dot path (e.g., "explore.define", "backlog")
        priority=issue.priority.value,
        tmux_active=tmux_active,
        has_worktree=bool(issue.worktree_dir),
        pr_url=issue.pr_url,
        pr_number=issue.pr_number,
        port=_config.get_port_for_issue(issue.id),
        created_at=datetime.fromisoformat(issue.created.replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(issue.updated.replace("Z", "+00:00")),
        dependencies=issue.dependencies,
        dependents=dependents,
        processing=issue.processing,
        ci_escalated=issue.ci_escalated,
        flow=issue.flow,
        time_in_stage=time_in_stage,
    )


def filter_issues(issues: list[WebIssue], search: Optional[str]) -> list[WebIssue]:
    """Filter issues by search query.

    Matches against issue number, title, and labels (case-insensitive).
    Returns all issues if search is None or empty.
    """
    if not search or not search.strip():
        return issues

    query = search.lower().strip()
    filtered = []
    for issue in issues:
        # Match against number
        if query in str(issue.number):
            filtered.append(issue)
            continue
        # Match against title
        if query in issue.title.lower():
            filtered.append(issue)
            continue
        # Match against labels
        if any(query in label.lower() for label in issue.labels):
            filtered.append(issue)
            continue
    return filtered


def get_kanban_board(search: Optional[str] = None) -> KanbanBoard:
    """Build a kanban board from issues.

    Each column is a dot-path substage (e.g., "explore.define", "implement.code").
    Stages without substages (e.g., "backlog", "accepted") get a single column.

    Args:
        search: Optional search query to filter issues
    """
    import logging

    logger = logging.getLogger("agenttree.web")

    dot_paths = _config.get_all_dot_paths()
    stages: dict[str, list[WebIssue]] = {path: [] for path in dot_paths}

    issues = issue_crud.list_issues(sync=False)
    web_issues = [convert_issue_to_web(issue) for issue in issues]

    if search:
        web_issues = filter_issues(web_issues, search)

    for web_issue in web_issues:
        if web_issue.stage in stages:
            stages[web_issue.stage].append(web_issue)
        else:
            logger.warning(
                "Issue #%s has unrecognized stage '%s', showing in backlog",
                web_issue.number,
                web_issue.stage,
            )
            if "backlog" in stages:
                stages["backlog"].append(web_issue)

    return KanbanBoard(stages=stages, total_issues=len(web_issues))


def get_issue_files(
    issue_id: int | str,
    include_content: bool = False,
    current_stage: str | None = None,
) -> list[dict[str, str]]:
    """Get list of markdown files for an issue.

    Returns list of dicts with keys: name, display_name, size, modified, stage, is_passed, short_name
    If include_content=True, also includes 'content' key with file contents.

    Files are ordered by workflow stage (problem.md first, then spec.md, etc.),
    with any unknown files at the end sorted alphabetically.
    If config.show_issue_yaml is True, issue.yaml is included at the end.

    Args:
        issue_id: The issue ID to get files for
        include_content: Whether to include file content
        current_stage: Current stage of the issue (for calculating is_passed)
    """
    issue_dir = issue_crud.get_issue_dir(issue_id)
    if not issue_dir:
        return []

    # Build file list
    file_list = list(issue_dir.glob("*.md"))

    # Sort by stage order, then alphabetically for unknown files
    def file_sort_key(f: Path) -> tuple[int, str]:
        if f.name in STAGE_FILE_ORDER:
            return (STAGE_FILE_ORDER.index(f.name), f.name)
        return (len(STAGE_FILE_ORDER), f.name)  # Unknown files sorted after known ones

    # Get current stage index for is_passed calculation using flow ordering.
    dot_paths = _config.get_flow_stage_names()
    current_stage_index = -1
    if current_stage and current_stage in dot_paths:
        current_stage_index = dot_paths.index(current_stage)

    files: list[dict[str, str]] = []
    for f in sorted(file_list, key=file_sort_key):
        display_name = f.stem.replace("_", " ").title()
        file_stage = FILE_TO_STAGE.get(f.name)

        # Calculate is_passed: file's stage is earlier than current stage.
        is_passed = False
        if file_stage and current_stage_index >= 0 and file_stage in dot_paths:
            file_stage_index = dot_paths.index(file_stage)
            is_passed = file_stage_index < current_stage_index

        # Generate short_name for passed stages (first 3 chars + "...")
        short_name = display_name
        if is_passed:
            short_name = display_name[:3] + "..."

        stage_color = (_config.stage_color(file_stage) or "") if file_stage else ""
        file_info: dict[str, str] = {
            "name": f.name,
            "display_name": display_name,
            "size": str(f.stat().st_size),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            "stage": file_stage or "",
            "stage_color": stage_color,
            "is_passed": str(is_passed).lower(),
            "short_name": short_name,
        }
        if include_content:
            try:
                file_info["content"] = f.read_text()
            except Exception:
                file_info["content"] = ""
        files.append(file_info)

    # Optionally include issue.yaml at the end
    if _config.show_issue_yaml:
        issue_yaml = issue_dir / "issue.yaml"
        if issue_yaml.exists():
            file_info = {
                "name": "issue.yaml",
                "display_name": "Issue YAML",
                "size": str(issue_yaml.stat().st_size),
                "modified": datetime.fromtimestamp(issue_yaml.stat().st_mtime).isoformat(),
                "stage": "",
                "stage_color": "",
                "is_passed": "false",
                "short_name": "Issue YAML",
            }
            if include_content:
                try:
                    file_info["content"] = issue_yaml.read_text()
                except Exception:
                    file_info["content"] = ""
            files.append(file_info)

    return files


def get_default_doc(dot_path: str, ci_escalated: bool = False) -> str | None:
    """Get the default document to show for a dot-path stage.

    Checks review_doc first (for human review stages), then output (the doc
    being produced), so the most relevant file is auto-selected.

    When ci_escalated=True and stage is implement.review, returns ci_feedback.md
    since that contains the escalation report that's most relevant for human review.
    """
    # When escalated, show the CI feedback report as the primary document
    if ci_escalated and dot_path == "implement.review":
        return "ci_feedback.md"

    stage_config, sub_config = _config.resolve_stage(dot_path)
    if sub_config and sub_config.review_doc:
        return sub_config.review_doc
    if stage_config and stage_config.review_doc:
        return stage_config.review_doc
    if sub_config and sub_config.output:
        return sub_config.output
    if stage_config and stage_config.output:
        return stage_config.output
    return None


def get_issue_diff(issue_id: int) -> dict:
    """Get git diff for an issue's worktree.

    Returns dict with keys: diff, stat, has_changes, error, truncated
    """
    issue = issue_crud.get_issue(issue_id)
    if not issue:
        return {
            "diff": "",
            "stat": "",
            "has_changes": False,
            "error": "Issue not found",
            "truncated": False,
        }

    if not issue.worktree_dir:
        return {
            "diff": "",
            "stat": "",
            "has_changes": False,
            "error": "No worktree for this issue",
            "truncated": False,
        }

    worktree_path = Path(issue.worktree_dir)
    if not worktree_path.exists():
        return {
            "diff": "",
            "stat": "",
            "has_changes": False,
            "error": "Worktree not found",
            "truncated": False,
        }

    try:
        # Get the diff (--no-color for speed, limit context lines)
        diff_result = subprocess.run(
            ["git", "diff", "--no-color", "-U3", "main...HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        diff_output = diff_result.stdout

        # Get the stat summary
        stat_result = subprocess.run(
            ["git", "diff", "--no-color", "--stat", "main...HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        stat_output = stat_result.stdout

        # Check for truncation
        truncated = False
        if len(diff_output) > MAX_DIFF_SIZE:
            diff_output = diff_output[:MAX_DIFF_SIZE]
            truncated = True

        has_changes = bool(diff_output.strip())

        # Count lines added/removed
        additions = 0
        deletions = 0
        files_changed = 0
        for line in diff_output.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
            elif line.startswith("diff --git"):
                files_changed += 1

        # Build PR diff URL if PR exists
        pr_diff_url = None
        if issue.pr_url:
            pr_diff_url = issue.pr_url + "/files"

        return {
            "diff": diff_output,
            "stat": stat_output,
            "has_changes": has_changes,
            "error": None,
            "truncated": truncated,
            "additions": additions,
            "deletions": deletions,
            "files_changed": files_changed,
            "pr_diff_url": pr_diff_url,
        }
    except subprocess.TimeoutExpired:
        return {
            "diff": "",
            "stat": "",
            "has_changes": False,
            "error": "Diff generation timed out",
            "truncated": False,
            "pr_diff_url": None,
        }
    except Exception as e:
        return {
            "diff": "",
            "stat": "",
            "has_changes": False,
            "error": str(e),
            "truncated": False,
            "pr_diff_url": None,
        }


def _sort_flow_issues(
    issues: list[WebIssue], sort_by: Optional[str] = None
) -> list[WebIssue]:
    """Sort issues for flow view based on sort parameter.

    Args:
        issues: List of WebIssue objects to sort
        sort_by: Sort method - 'stage' (default), 'updated', 'created', 'number'

    Returns:
        Sorted list of issues
    """
    if sort_by == "updated":
        # Newest updated first
        return sorted(issues, key=lambda x: x.updated_at, reverse=True)
    elif sort_by == "created":
        # Newest created first
        return sorted(issues, key=lambda x: x.created_at, reverse=True)
    elif sort_by == "number":
        # Issue number ascending
        return sorted(issues, key=lambda x: x.number)
    else:
        # Default: stage order with review stages first
        # Use flow dot paths for ordering; unknown stages sort last
        dot_paths = _config.get_flow_stage_names()

        def _stage_sort_key(x: WebIssue) -> tuple[bool, int, int]:
            try:
                idx = dot_paths.index(x.stage)
            except ValueError:
                idx = -1  # Unknown stages sort last (after negation: first in reverse)
            return (not x.is_review, -idx, x.number)

        return sorted(issues, key=_stage_sort_key)


def _filter_flow_issues(
    issues: list[WebIssue], filter_by: Optional[str] = None
) -> list[WebIssue]:
    """Filter issues for flow view based on filter parameter.

    Args:
        issues: List of WebIssue objects to filter
        filter_by: Filter method - 'all' (default), 'review', 'running', 'open', 'active'

    Returns:
        Filtered list of issues
    """
    if filter_by == "review":
        # Only review stages
        return [i for i in issues if i.is_review]
    elif filter_by == "running":
        # Only issues with active agents
        return [i for i in issues if i.tmux_active]
    elif filter_by == "open":
        # Hide parking-lot stages (accepted, not_doing, etc.)
        parking_lots = _config.get_parking_lot_stages()
        return [
            i for i in issues if _config.stage_group_name(i.stage) not in parking_lots
        ]
    elif filter_by == "active":
        # Only issues where an agent should be actively working
        # Filters out parking lots, human review stages, manager stages
        return [
            i
            for i in issues
            if not _config.is_parking_lot(i.stage)
            and not _config.is_human_review(i.stage)
            and _config.role_for(i.stage) != "manager"
        ]
    else:
        # Default: show all
        return issues


def _get_flow_issues(
    search: str | None = None, sort: str | None = None, filter_by: str | None = None
) -> list[WebIssue]:
    """Sync helper that loads and converts issues for flow/mobile views.

    This function is called via asyncio.to_thread() to avoid blocking the event loop
    during subprocess calls in convert_issue_to_web().
    """
    agent_manager.clear_session_cache()  # Fresh session data per request
    issues = issue_crud.list_issues(sync=False)
    web_issues = [convert_issue_to_web(i) for i in issues]
    web_issues = _filter_flow_issues(web_issues, filter_by)
    web_issues = _sort_flow_issues(web_issues, sort)
    if search:
        web_issues = filter_issues(web_issues, search)
    return web_issues


def _capture_tmux_output(session_names: list[str]) -> tuple[str | None, str | None]:
    """Sync helper that captures tmux output from session.

    This function is called via asyncio.to_thread() to avoid blocking the event loop
    during subprocess calls.

    Returns:
        Tuple of (output, session_name) or (None, None) if no session found.
    """
    from agenttree.tmux import capture_pane

    for name in session_names:
        output = capture_pane(name, lines=100)
        if output:  # capture_pane returns "" on error
            return output, name
    return None, None
