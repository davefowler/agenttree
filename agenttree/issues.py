"""Issue management for AgentTree.

This module handles CRUD operations for issues stored in _agenttree/issues/.
"""

import logging
import re
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, PrivateAttr, field_validator

from agenttree.agents_repo import sync_agents_repo

log = logging.getLogger("agenttree.issues")

# Per-file mtime cache: only re-parse YAML files whose mtime changed.
# Turns 146 YAML parses (~500ms) into 146 stat() calls (~1.5ms).
_issue_file_cache: dict[Path, tuple[float, "Issue"]] = {}


def invalidate_issues_cache() -> None:
    """Clear the list_issues cache (call after any write to issue YAML)."""
    _issue_file_cache.clear()


def resolve_conflict_markers(content: str) -> tuple[str, bool]:
    """Resolve git merge conflict markers in content by keeping local (ours) changes.

    Handles conflict blocks like:
        <<<<<<< Updated upstream
        remote content
        =======
        local content
        >>>>>>> Stashed changes

    Args:
        content: File content that may contain conflict markers

    Returns:
        Tuple of (resolved_content, had_conflicts)
    """
    # Pattern matches conflict blocks and captures local (ours) content
    # Conflict markers can have various suffixes (HEAD, Updated upstream, Stashed changes, etc.)
    pattern = re.compile(
        r'<{7}[^\n]*\n'      # <<<<<<< marker with optional suffix
        r'(?:.*?\n)*?'       # remote/theirs content (non-greedy)
        r'={7}\n'            # ======= separator
        r'((?:.*?\n)*?)'     # local/ours content (captured)
        r'>{7}[^\n]*\n?',    # >>>>>>> marker with optional suffix
        re.DOTALL
    )

    resolved, count = pattern.subn(r'\1', content)
    return resolved, count > 0


def safe_yaml_load(file_path: Path | str) -> Any:
    """Load YAML file with automatic git conflict marker resolution.

    If the file contains git merge conflict markers (from failed stash pop,
    merge, etc.), this function automatically resolves them by keeping the
    local (ours) changes and logs a warning.

    Args:
        file_path: Path to YAML file

    Returns:
        Parsed YAML content

    Raises:
        FileNotFoundError: If file doesn't exist
        yaml.YAMLError: If YAML parsing fails after conflict resolution
    """
    path = Path(file_path)
    content = path.read_text()

    # Check for and resolve conflict markers
    resolved_content, had_conflicts = resolve_conflict_markers(content)

    if had_conflicts:
        log.warning(
            "Auto-resolved git conflict markers in %s (kept local changes)",
            path.name
        )
        # Write the resolved content back to fix the file
        path.write_text(resolved_content)

    return yaml.safe_load(resolved_content)


class Priority(str, Enum):
    """Issue priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class HistoryEntry(BaseModel):
    """A single entry in issue history."""
    stage: str  # Dot path (e.g., "explore.define", "backlog")
    timestamp: str
    agent: Optional[int] = None
    type: str = "transition"  # "transition" (normal), "rollback", etc.


class Issue(BaseModel):
    """An issue in the agenttree workflow."""
    _yaml_path: Path | None = PrivateAttr(default=None)

    id: int
    slug: str = ""
    title: str = ""
    created: str = ""
    updated: str = ""

    stage: str = "explore.define"  # Dot path (e.g., "explore.define", "backlog")
    flow: str = "default"  # Which workflow flow this issue follows

    branch: Optional[str] = None
    worktree_dir: Optional[str] = None  # Absolute path to worktree directory

    labels: list[str] = Field(default_factory=list)
    priority: Priority = Priority.MEDIUM

    # Dependencies: list of issue IDs that must be completed (accepted stage) before this issue can start
    dependencies: list[int] = Field(default_factory=list)

    github_issue: Optional[int] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    relevant_url: Optional[str] = None

    history: list[HistoryEntry] = Field(default_factory=list)

    agent_ensured: Optional[str] = None  # Dot path where custom agent was ensured
    needs_ui_review: bool = False  # If True, ui_review substage will run

    # Processing state: "exit", "enter", or None (not processing)
    processing: Optional[str] = None

    # Set when CI fails too many times and issue is escalated to human review
    ci_escalated: bool = False

    # Tracks whether CI notification was sent for current PR check run
    ci_notified: Optional[bool] = None

    # Guard for manager hook re-entry (e.g., "implement.review", "implement.review:running")
    manager_hooks_executed: Optional[str] = None

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id_to_int(cls, v: Any) -> int:
        """Coerce string IDs to int for backwards compatibility.

        Handles legacy string IDs like '042' from old YAML files.
        """
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            return int(v.lstrip("0") or "0")
        raise ValueError(f"Invalid issue ID: {v}")

    @field_validator("dependencies", mode="before")
    @classmethod
    def _coerce_dependencies_to_int(cls, v: Any) -> list[int]:
        """Coerce string dependency IDs to int for backwards compatibility."""
        if not v:
            return []
        result = []
        for dep in v:
            if isinstance(dep, int):
                result.append(dep)
            elif isinstance(dep, str):
                result.append(int(dep.lstrip("0") or "0"))
            else:
                raise ValueError(f"Invalid dependency ID: {dep}")
        return result

    @field_validator("created", "updated", mode="before")
    @classmethod
    def _coerce_date_to_str(cls, v: Any) -> Any:
        """Coerce datetime.date/datetime objects to ISO strings.

        PyYAML auto-parses unquoted dates like `2026-01-11` into datetime.date
        objects. Convert them to strings so Pydantic validation passes.
        """
        if isinstance(v, datetime):
            return v.isoformat()
        if hasattr(v, "isoformat"):  # datetime.date
            return v.isoformat()
        return v

    @property
    def dir_name(self) -> str:
        """Get directory name for this issue (e.g., '042')."""
        from agenttree.ids import format_issue_id
        return format_issue_id(self.id)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "Issue":
        """Load an Issue from a YAML file.

        Args:
            path: Path to issue.yaml file

        Returns:
            Issue object with _yaml_path set

        Raises:
            FileNotFoundError: If file doesn't exist
            pydantic.ValidationError: If data is invalid
        """
        p = Path(path)
        data = safe_yaml_load(p)
        issue = cls(**data)
        issue._yaml_path = p
        return issue

    def save(self) -> None:
        """Write this issue to its YAML file and invalidate cache.

        Uses exclude_none=True so None-valued fields are omitted from YAML.
        This means setting a field to None effectively removes it on save.

        Raises:
            RuntimeError: If _yaml_path is not set
        """
        if self._yaml_path is None:
            raise RuntimeError("Cannot save: _yaml_path not set (use from_yaml or set _yaml_path)")
        data = self.model_dump(exclude_none=True, mode="json")
        with open(self._yaml_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        _issue_file_cache.pop(self._yaml_path, None)

    @property
    def dir(self) -> Path | None:
        """Issue directory path, derived from _yaml_path."""
        if self._yaml_path is not None:
            return self._yaml_path.parent
        return None

    @classmethod
    def get(cls, issue_id: int | str, sync: bool = True) -> Optional["Issue"]:
        """Get an issue by ID.

        Convenience wrapper around get_issue(). Looks up the issue directory
        and loads from YAML.

        Args:
            issue_id: Issue ID (e.g., "001", "42", or "001-fix-login")
            sync: If True, sync with remote before reading

        Returns:
            Issue object or None if not found
        """
        return get_issue(issue_id, sync=sync)


def slugify(text: str) -> str:
    """Convert text to a URL-friendly slug."""
    # Lowercase and replace spaces with hyphens
    slug = text.lower().strip()
    # Remove special characters
    slug = re.sub(r'[^\w\s-]', '', slug)
    # Replace whitespace with hyphens
    slug = re.sub(r'[\s_]+', '-', slug)
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    # Limit length
    return slug[:50]


def get_agenttree_path() -> Path:
    """Get the path to _agenttree directory.

    In worktrees, _agenttree is gitignored so we need to find it in the main repo.
    """
    cwd = Path.cwd()
    local_path = cwd / "_agenttree"

    # If local _agenttree has content (or is a symlink), use it
    if local_path.exists():
        # Check if it's a symlink or has issues subdirectory
        if local_path.is_symlink() or (local_path / "issues").exists():
            return local_path

    # In a worktree, .git is a file pointing to the main repo
    git_path = cwd / ".git"
    if git_path.is_file():
        # Parse gitdir from .git file: "gitdir: /path/to/main/.git/worktrees/xxx"
        content = git_path.read_text().strip()
        if content.startswith("gitdir:"):
            gitdir = Path(content.split(":", 1)[1].strip())
            # Go up from .git/worktrees/xxx to main repo root
            main_repo = gitdir.parent.parent.parent
            main_agenttree = main_repo / "_agenttree"
            if main_agenttree.exists():
                return main_agenttree

    # No worktree .git, use local path
    return local_path


def get_issues_path() -> Path:
    """Get the path to issues directory."""
    return get_agenttree_path() / "issues"


def get_next_issue_number() -> int:
    """Get the next available issue number."""
    issues_path = get_issues_path()
    if not issues_path.exists():
        return 1

    max_num = 0
    for issue_dir in issues_path.iterdir():
        if issue_dir.is_dir() and issue_dir.name != "archive":
            # Directory name is just the number (e.g., "001", "042", "1001")
            try:
                num = int(issue_dir.name)
                max_num = max(max_num, num)
            except ValueError:
                # Skip directories that aren't valid issue IDs
                continue

    return max_num + 1


def sanitize_filename(filename: str) -> str:
    """Sanitize a filename for safe storage.

    Removes path traversal attempts, replaces unsafe characters,
    and adds a timestamp prefix for uniqueness.

    Args:
        filename: Original filename from user upload

    Returns:
        Safe filename with timestamp prefix
    """
    # Remove path components (handles both / and \)
    filename = filename.replace("\\", "/")
    filename = filename.split("/")[-1]

    # Remove leading dots (hidden files, path traversal)
    filename = filename.lstrip(".")

    # Replace unsafe characters with underscores
    unsafe_chars = '<>:"|?*'
    for char in unsafe_chars:
        filename = filename.replace(char, "_")

    # Replace spaces with underscores
    filename = filename.replace(" ", "_")

    # Ensure we have something left
    if not filename:
        filename = "attachment"

    # Add timestamp prefix for uniqueness
    timestamp = int(time.time())
    return f"{timestamp}_{filename}"


def create_issue(
    title: str,
    priority: Priority = Priority.MEDIUM,
    labels: Optional[list[str]] = None,
    stage: str = "explore.define",
    flow: str = "default",
    problem: Optional[str] = None,
    context: Optional[str] = None,
    solutions: Optional[str] = None,
    dependencies: Optional[list[int | str]] = None,
    needs_ui_review: bool = False,
    attachments: list[tuple[str, bytes]] | None = None,
) -> Issue:
    """Create a new issue.

    Args:
        title: Issue title
        priority: Issue priority
        labels: Optional list of labels
        stage: Starting stage dot path (default: "explore.define")
        flow: Workflow flow for this issue (default: "default")
        problem: Problem statement text (fills problem.md)
        context: Context/background text (fills problem.md)
        solutions: Possible solutions text (fills problem.md)
        dependencies: Optional list of issue IDs that must be completed first
        needs_ui_review: If True, ui_review substage will run for this issue
        attachments: Optional list of (filename, content) tuples to attach

    Returns:
        The created Issue object
    """
    from agenttree.ids import format_issue_id, parse_issue_id

    # Sync before and after writing
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=True)

    issues_path = get_issues_path()
    issues_path.mkdir(parents=True, exist_ok=True)

    # Generate ID
    issue_id = get_next_issue_number()
    slug = slugify(title)
    dir_name = format_issue_id(issue_id)

    # Create issue directory
    issue_dir = issues_path / dir_name
    issue_dir.mkdir(exist_ok=True)

    # Convert dependencies to ints
    deps_int: list[int] = []
    if dependencies:
        for dep in dependencies:
            if isinstance(dep, int):
                deps_int.append(dep)
            else:
                deps_int.append(parse_issue_id(dep))

        # Check for circular dependencies before creating
        cycle = detect_circular_dependency(issue_id, deps_int)
        if cycle:
            cycle_str = " -> ".join(format_issue_id(c) for c in cycle)
            raise ValueError(f"Circular dependency detected: {cycle_str}")

    # Create issue object
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue = Issue(
        id=issue_id,
        slug=slug,
        title=title,
        created=now,
        updated=now,
        stage=stage,
        flow=flow,
        priority=priority,
        labels=labels or [],
        dependencies=deps_int,
        needs_ui_review=needs_ui_review,
        history=[
            HistoryEntry(stage=stage, timestamp=now)
        ]
    )

    # Write issue.yaml
    issue._yaml_path = issue_dir / "issue.yaml"
    issue.save()

    # Create problem.md - use provided content or template
    problem_path = issue_dir / "problem.md"

    if problem or context or solutions:
        # Build problem.md from provided content
        content = "# Problem Statement\n\n"
        content += problem or f"<!-- Describe the problem: {title} -->\n"
        content += "\n\n## Context\n\n"
        content += context or "<!-- Background and relevant file paths -->\n"
        content += "\n\n## Possible Solutions\n\n"
        content += solutions or "<!-- List at least one approach -->\n\n-"
        content += "\n"
        problem_path.write_text(content)
    else:
        # Use template or fallback
        template_path = get_agenttree_path() / "templates" / "problem.md"
        if template_path.exists():
            problem_path.write_text(template_path.read_text())
        else:
            # Fallback template
            problem_path.write_text(f"""# Problem Statement

<!-- Describe the problem: {title} -->



## Context

<!-- Background and relevant file paths -->



## Possible Solutions

<!-- List at least one approach -->

-

""")

    # Save attachments if provided
    if attachments:
        attachments_dir = issue_dir / "attachments"
        attachments_dir.mkdir(exist_ok=True)

        # Image extensions that should use image markdown syntax
        image_extensions = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}

        attachment_lines: list[str] = []
        for attachment in attachments:
            filename = attachment[0]
            file_content = attachment[1]
            # Sanitize and save the file
            safe_filename = sanitize_filename(filename)
            file_path = attachments_dir / safe_filename
            file_path.write_bytes(file_content)

            # Determine markdown syntax based on file type
            ext = Path(filename).suffix.lower()
            relative_path = f"attachments/{safe_filename}"

            if ext in image_extensions:
                # Image syntax: ![alt](path)
                attachment_lines.append(f"![{filename}]({relative_path})")
            else:
                # Link syntax: [name](path)
                attachment_lines.append(f"[{filename}]({relative_path})")

        # Append attachments section to problem.md
        attachments_section = "\n\n## Attachments\n\n" + "\n".join(attachment_lines) + "\n"
        with open(problem_path, "a") as f:
            f.write(attachments_section)

    # Sync after creating issue
    sync_agents_repo(agents_path, pull_only=False, commit_message=f"Create issue {issue_id}: {title}")

    return issue


def _load_all_issues() -> list[Issue]:
    """Read all issue YAML files, using per-file mtime cache.

    Only re-parses YAML files whose mtime changed since last read.
    Stale cache entries (deleted issues) are pruned each call.
    """
    issues_path = get_issues_path()
    if not issues_path.exists():
        return []

    seen_paths: set[Path] = set()
    issues: list[Issue] = []

    for issue_dir in sorted(issues_path.iterdir()):
        if not issue_dir.is_dir() or issue_dir.name == "archive":
            continue

        yaml_path = issue_dir / "issue.yaml"
        if not yaml_path.exists():
            continue

        seen_paths.add(yaml_path)
        mtime = yaml_path.stat().st_mtime

        cached = _issue_file_cache.get(yaml_path)
        if cached is not None and cached[0] == mtime:
            issues.append(cached[1])
            continue

        try:
            issue = Issue.from_yaml(yaml_path)
        except Exception:
            continue

        _issue_file_cache[yaml_path] = (mtime, issue)
        issues.append(issue)

    # Prune cache entries for deleted issues
    stale = set(_issue_file_cache) - seen_paths
    for p in stale:
        del _issue_file_cache[p]

    return issues


def list_issues(
    stage: Optional[str] = None,
    priority: Optional[Priority] = None,
    sync: bool = True,
) -> list[Issue]:
    """List issues, optionally filtered.

    Args:
        stage: Filter by stage
        priority: Filter by priority
        sync: If True, sync with remote before reading (default True for CLI, False for web)

    Returns:
        List of Issue objects
    """
    if sync:
        agents_path = get_agenttree_path()
        sync_agents_repo(agents_path, pull_only=True)
        invalidate_issues_cache()

    issues = _load_all_issues()

    if stage or priority:
        issues = [
            i for i in issues
            if (not stage or i.stage == stage)
            and (not priority or i.priority == priority)
        ]

    return issues


def get_issue(issue_id: int | str, sync: bool = True) -> Optional[Issue]:
    """Get a single issue by ID.

    Routes through _load_all_issues() to benefit from the mtime cache.

    Args:
        issue_id: Issue ID (int or string like "042", "42")
        sync: If True, sync with remote before reading (default True for CLI, False for web)

    Returns:
        Issue object or None if not found
    """
    if sync:
        agents_path = get_agenttree_path()
        sync_agents_repo(agents_path, pull_only=True)
        invalidate_issues_cache()

    # Normalize to int
    from agenttree.ids import parse_issue_id
    if isinstance(issue_id, str):
        target_id = parse_issue_id(issue_id)
    else:
        target_id = issue_id

    for issue in _load_all_issues():
        if issue.id == target_id:
            return issue

    return None


def get_issue_dir(issue_id: int | str) -> Optional[Path]:
    """Get the directory path for an issue.

    Args:
        issue_id: Issue ID (int or string)

    Returns:
        Path to issue directory or None
    """
    from agenttree.ids import parse_issue_id, format_issue_id

    issues_path = get_issues_path()
    if not issues_path.exists():
        return None

    # Normalize to int, then format as directory name
    if isinstance(issue_id, str):
        target_id = parse_issue_id(issue_id)
    else:
        target_id = issue_id

    dir_name = format_issue_id(target_id)
    issue_dir = issues_path / dir_name

    if issue_dir.exists() and issue_dir.is_dir():
        return issue_dir

    return None


def check_dependencies_met(issue: Issue) -> tuple[bool, list[int]]:
    """Check if all dependencies for an issue are met.

    A dependency is met when the dependent issue is in the ACCEPTED stage.

    Args:
        issue: Issue to check dependencies for

    Returns:
        Tuple of (all_met, unmet_ids) where:
        - all_met: True if all dependencies are met
        - unmet_ids: List of issue IDs (int) that are not yet completed
    """
    if not issue.dependencies:
        return True, []

    unmet: list[int] = []
    for dep_id in issue.dependencies:
        dep_issue = get_issue(dep_id, sync=False)
        if dep_issue is None:
            # Dependency doesn't exist - treat as unmet
            unmet.append(dep_id)
        elif dep_issue.stage != "accepted":
            unmet.append(dep_id)

    return len(unmet) == 0, unmet


def remove_dependency(issue_id: int | str, dep_id: int | str) -> Optional[Issue]:
    """Remove a dependency from an issue.

    Args:
        issue_id: Issue to remove dependency from
        dep_id: Dependency issue ID to remove

    Returns:
        Updated Issue object or None if not found
    """
    from agenttree.ids import parse_issue_id

    # Sync before and after writing
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=True)

    issue_dir = get_issue_dir(issue_id)
    if not issue_dir:
        return None

    yaml_path = issue_dir / "issue.yaml"
    if not yaml_path.exists():
        return None

    issue = Issue.from_yaml(yaml_path)

    # Normalize dep_id to int
    if isinstance(dep_id, str):
        dep_int = parse_issue_id(dep_id)
    else:
        dep_int = dep_id

    # Remove the dependency
    if dep_int in issue.dependencies:
        issue.dependencies.remove(dep_int)

    # Update timestamp
    issue.updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    issue.save()

    sync_agents_repo(agents_path)
    return issue


def detect_circular_dependency(
    issue_id: int | str,
    new_dependencies: list[int],
) -> Optional[list[int]]:
    """Detect if adding dependencies would create a circular dependency.

    Uses DFS to detect cycles in the dependency graph.

    Args:
        issue_id: The issue ID to check
        new_dependencies: List of dependency IDs to validate

    Returns:
        List of issue IDs forming the cycle if found, None otherwise
    """
    from agenttree.ids import parse_issue_id

    if not new_dependencies:
        return None

    # Normalize issue ID to int
    if isinstance(issue_id, str):
        target_id = parse_issue_id(issue_id)
    else:
        target_id = issue_id

    # Build adjacency list of all existing dependencies
    dep_graph: dict[int, list[int]] = {}
    for issue in list_issues(sync=False):
        dep_graph[issue.id] = issue.dependencies.copy()

    # Add the new dependencies we're validating
    dep_graph[target_id] = new_dependencies.copy()

    # DFS to detect cycle starting from issue_id
    visited: set[int] = set()
    path: list[int] = []
    path_set: set[int] = set()

    def dfs(node: int) -> Optional[list[int]]:
        if node in path_set:
            # Found cycle - return path from cycle start
            cycle_start = path.index(node)
            return path[cycle_start:] + [node]

        if node in visited:
            return None

        visited.add(node)
        path.append(node)
        path_set.add(node)

        for neighbor in dep_graph.get(node, []):
            cycle = dfs(neighbor)
            if cycle:
                return cycle

        path.pop()
        path_set.remove(node)
        return None

    return dfs(target_id)


def get_blocked_issues(completed_issue_id: int | str) -> list[Issue]:
    """Get all issues in backlog that were waiting on a completed issue.

    Args:
        completed_issue_id: ID of the issue that was just completed

    Returns:
        List of issues that have this issue as a dependency
    """
    from agenttree.ids import parse_issue_id

    # Normalize to int
    if isinstance(completed_issue_id, str):
        target_id = parse_issue_id(completed_issue_id)
    else:
        target_id = completed_issue_id

    blocked = []
    for issue in list_issues(stage="backlog", sync=False):
        if target_id in issue.dependencies:
            blocked.append(issue)

    return blocked


def get_dependent_issues(issue_id: int | str) -> list[Issue]:
    """Get all issues that depend on this issue (any stage).

    Unlike get_blocked_issues which only returns backlog issues,
    this returns ALL issues that have this issue in their dependencies.

    Args:
        issue_id: ID of the issue to find dependents for

    Returns:
        List of issues that depend on this issue
    """
    from agenttree.ids import parse_issue_id

    # Normalize to int
    if isinstance(issue_id, str):
        target_id = parse_issue_id(issue_id)
    else:
        target_id = issue_id

    dependents = []
    for issue in list_issues(sync=False):
        if target_id in issue.dependencies:
            dependents.append(issue)

    return dependents


def get_ready_issues() -> list[Issue]:
    """Get all issues in backlog that have all dependencies met and can be started.

    Returns:
        List of issues that are ready to start
    """
    ready = []
    for issue in list_issues(stage="backlog"):
        if issue.dependencies:
            all_met, _ = check_dependencies_met(issue)
            if all_met:
                ready.append(issue)
        # Issues without dependencies in backlog can also be started
        # but they were likely put there intentionally, so don't auto-start

    return ready


def get_next_stage(
    current: str,
    flow: str = "default",
    issue_context: dict | None = None,
) -> tuple[str, bool]:
    """Calculate the next stage from a dot path.

    Delegates to Config.get_next_stage() for config-driven workflow.

    Args:
        current: Current dot path (e.g., "explore.define")
        flow: Workflow flow to use for stage progression (default: "default")
        issue_context: Optional dict of issue context for condition evaluation

    Returns:
        Tuple of (next_dot_path, is_human_review)
    """
    from agenttree.config import load_config

    config = load_config()
    return config.get_next_stage(current, flow, issue_context)


def update_issue_stage(
    issue_id: int | str,
    stage: str,
    agent: Optional[int] = None,
    skip_sync: bool = False,
    history_type: Optional[str] = None,
    clear_pr: bool = False,
    ci_escalated: Optional[bool] = None,
    _issue_dir: Optional[Path] = None,
) -> Optional[Issue]:
    """Update an issue's stage.

    Args:
        issue_id: Issue ID
        stage: New stage dot path (e.g., "explore.define", "implement.code")
        agent: Agent number making the change (optional)
        skip_sync: If True, skip syncing to remote (for heartbeat callers
            that would otherwise cause recursion via sync_agents_repo)
        history_type: Optional type for history entry (e.g., "rollback")
        clear_pr: If True, clear pr_number and pr_url
        ci_escalated: If provided, set ci_escalated flag
        _issue_dir: If provided, use this directory instead of looking up via
            get_issue_dir. For internal callers that already know the path.

    Returns:
        Updated Issue object or None if not found
    """
    # Validate stage exists in config to catch renames/typos early
    from agenttree.config import load_config
    try:
        config = load_config()
        group = config.stage_group_name(stage)
        stage_names = config.get_stage_names()
        if group not in stage_names:
            log.warning("Stage '%s' (group '%s') does not exist in config — "
                        "issue #%s may become invisible on kanban board", stage, group, issue_id)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as e:
        log.debug("Stage validation skipped (config unavailable): %s", e)

    if not skip_sync:
        agents_path = get_agenttree_path()
        sync_agents_repo(agents_path, pull_only=True)

    issue_dir = _issue_dir or get_issue_dir(issue_id)
    if not issue_dir:
        return None

    yaml_path = issue_dir / "issue.yaml"
    if not yaml_path.exists():
        return None

    issue = Issue.from_yaml(yaml_path)
    old_stage = issue.stage

    # Update stage
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue.stage = stage
    issue.updated = now

    # Clear ci_escalated when leaving implement.review
    if old_stage == "implement.review" and stage != "implement.review":
        issue.ci_escalated = False

    # Clear ci_notified when entering ci_wait so new CI runs get detected
    # (save() uses exclude_none=True, so setting to None omits the field)
    if stage == "implement.ci_wait":
        issue.ci_notified = None

    # Explicit overrides from caller
    if ci_escalated is not None:
        issue.ci_escalated = ci_escalated
    if clear_pr:
        issue.pr_number = None
        issue.pr_url = None

    # Add history entry
    entry_kwargs: dict[str, Any] = {"stage": stage, "timestamp": now}
    if agent is not None:
        entry_kwargs["agent"] = agent
    if history_type is not None:
        entry_kwargs["type"] = history_type
    history_entry = HistoryEntry(**entry_kwargs)
    issue.history.append(history_entry)

    issue.save()

    if not skip_sync:
        agents_path = get_agenttree_path()
        sync_agents_repo(agents_path, pull_only=False, commit_message=f"Update issue {issue_id} to stage {stage}")

    return issue


def update_issue_metadata(
    issue_id: int | str,
    pr_number: Optional[int] = None,
    pr_url: Optional[str] = None,
    branch: Optional[str] = None,
    github_issue: Optional[int] = None,
    relevant_url: Optional[str] = None,
    worktree_dir: Optional[str] = None,
    clear_pr: bool = False,
    priority: Optional[Priority] = None,
    commit_message: Optional[str] = None,
    needs_ui_review: Optional[bool] = None,
) -> Optional[Issue]:
    """Update metadata fields on an issue.

    Args:
        issue_id: Issue ID
        pr_number: PR number (optional)
        pr_url: PR URL (optional)
        branch: Branch name (optional)
        github_issue: GitHub issue number (optional)
        relevant_url: Relevant URL (optional)
        worktree_dir: Worktree directory path (optional)
        clear_pr: If True, sets pr_number and pr_url to None
        priority: Priority level (optional)
        commit_message: Custom commit message (optional, defaults to generic)
        needs_ui_review: If True, ui_review stage will run (optional)

    Returns:
        Updated Issue object or None if not found
    """
    # Sync before and after writing
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=True)

    issue_dir = get_issue_dir(issue_id)
    if not issue_dir:
        return None

    yaml_path = issue_dir / "issue.yaml"
    if not yaml_path.exists():
        return None

    issue = Issue.from_yaml(yaml_path)

    # Update fields if provided
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if pr_number is not None:
        issue.pr_number = pr_number
    if pr_url is not None:
        issue.pr_url = pr_url
    if branch is not None:
        issue.branch = branch
    if github_issue is not None:
        issue.github_issue = github_issue
    if relevant_url is not None:
        issue.relevant_url = relevant_url
    if worktree_dir is not None:
        issue.worktree_dir = worktree_dir
    if clear_pr:
        issue.pr_number = None
        issue.pr_url = None
    if priority is not None:
        issue.priority = priority
    if needs_ui_review is not None:
        issue.needs_ui_review = needs_ui_review
    issue.updated = now

    issue.save()

    # Sync after updating metadata
    msg = commit_message or f"Update issue {issue_id} metadata"
    sync_agents_repo(agents_path, pull_only=False, commit_message=msg)

    return issue


def set_processing(issue_id: int | str, processing_state: str | None) -> bool:
    """Set or clear the processing state for an issue.

    Used to indicate that hooks are currently running on an issue.
    Pass None to clear the processing state after hooks complete.
    Does NOT sync to remote - processing state is transient and local only.

    Args:
        issue_id: Issue ID
        processing_state: Processing state to set (e.g., "exit", "enter"), or None to clear

    Returns:
        True if successful, False if issue not found
    """
    issue_dir = get_issue_dir(issue_id)
    if not issue_dir:
        return False

    yaml_path = issue_dir / "issue.yaml"
    if not yaml_path.exists():
        return False

    issue = Issue.from_yaml(yaml_path)
    issue.processing = processing_state
    issue.save()

    return True


def update_issue_priority(issue_id: int | str, priority: Priority) -> Optional[Issue]:
    """Update an issue's priority.

    Args:
        issue_id: Issue ID
        priority: New priority level

    Returns:
        Updated Issue object or None if not found
    """
    return update_issue_metadata(
        issue_id,
        priority=priority,
        commit_message=f"Update issue {issue_id} priority to {priority.value}"
    )


def get_issue_from_branch() -> Optional[str]:
    """Get issue ID from current git branch name.

    Parses branch names like:
    - issue-042-add-dark-mode → "042"
    - 042-add-dark-mode → "042"
    - feature/042-fix-bug → "042"

    Returns:
        Issue ID string or None if not found
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        branch = result.stdout.strip()
    except subprocess.CalledProcessError:
        return None

    # Try various patterns
    patterns = [
        r'issue-(\d+)',      # issue-042-slug
        r'^(\d{3})-',        # 042-slug
        r'/(\d{3})-',        # feature/042-slug
        r'-(\d{3})-',        # prefix-042-slug
    ]

    for pattern in patterns:
        match = re.search(pattern, branch)
        if match:
            return match.group(1)

    return None


def load_skill(
    dot_path: str,
    issue: Optional["Issue"] = None,
    include_system: bool = False,
) -> Optional[str]:
    """Load skill/instructions for a stage, rendered with Jinja if issue provided.

    Uses Config.skill_path() for resolving skill file locations.
    Convention: skills/{stage}/{substage}.md or skills/{stage}.md

    Args:
        dot_path: Stage dot path (e.g., "explore.define", "implement.code")
        issue: Optional Issue object for Jinja context
        include_system: If True, prepend AGENTS.md system prompt (for first stage)

    Returns:
        Skill content as string (rendered if issue provided), or None if not found

    Raises:
        FileNotFoundError: If config explicitly specifies a skill path that doesn't exist
    """
    from jinja2 import Template
    from agenttree.config import load_config

    # Sync before reading
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=True)

    config = load_config()
    stage_name, substage_name = config.parse_stage(dot_path)

    # Check if skill is explicitly configured (not convention-based)
    stage_config = config.get_stage(stage_name)
    explicit_skill = None
    if substage_name and stage_config:
        substage_config = stage_config.get_substage(substage_name)
        if substage_config and substage_config.skill:
            explicit_skill = substage_config.skill
    if not explicit_skill and stage_config and stage_config.skill:
        explicit_skill = stage_config.skill

    # Get skill path from config
    skill_rel_path = config.skill_path(dot_path)
    skill_path = agents_path / skill_rel_path

    skill_content = None

    # Try the config-specified path first
    if skill_path.exists():
        skill_content = skill_path.read_text()
    elif explicit_skill:
        # Config explicitly specified this skill file - it MUST exist
        raise FileNotFoundError(
            f"Skill file '{explicit_skill}' configured for stage '{dot_path}' "
            f"does not exist at {skill_path}"
        )
    else:
        # Try legacy naming convention: {stage}-{substage}.md
        skills_dir = agents_path / "skills"
        if substage_name:
            legacy_path = skills_dir / f"{stage_name}-{substage_name}.md"
            if legacy_path.exists():
                skill_content = legacy_path.read_text()

        # Fall back to stage skill without substage
        if skill_content is None:
            stage_skill = skills_dir / f"{stage_name}.md"
            if stage_skill.exists():
                skill_content = stage_skill.read_text()

    if skill_content is None:
        return None

    # Prepend system prompt if requested
    if include_system:
        system_path = agents_path / "skills" / "AGENTS.md"
        if system_path.exists():
            system_content = system_path.read_text()
            skill_content = system_content + "\n\n---\n\n" + skill_content

    # If no issue provided, return raw content
    if issue is None:
        return skill_content

    # Build Jinja context using unified function
    context = get_issue_context(issue, include_docs=True)

    # Override stage with what was passed to load_skill
    # (may differ from current issue state when loading a specific stage skill)
    context["stage"] = dot_path
    # Also provide parsed components for templates that need them
    context["stage_group"] = stage_name
    context["substage"] = substage_name or ""

    # Load project-level review checklist if it exists
    project_review_path = agents_path / "skills" / "project_review.md"
    if project_review_path.exists():
        context["project_review_md"] = project_review_path.read_text()
    else:
        context["project_review_md"] = ""

    # Inject command outputs for referenced commands
    from agenttree.commands import get_referenced_commands, get_command_output
    from agenttree.hooks import get_code_directory

    issue_dir = get_issue_dir(issue.id)
    if config.commands:
        cwd = get_code_directory(issue, issue_dir) if issue_dir else None
        referenced = get_referenced_commands(skill_content, config.commands)

        for cmd_name in referenced:
            if cmd_name not in context:
                context[cmd_name] = get_command_output(
                    config.commands, cmd_name, cwd=cwd
                )

    # Add available flows from config (for define stage flow selection)
    context["available_flows"] = list(config.flows.keys())
    context["default_flow"] = config.default_flow

    # Render with Jinja
    try:
        template = Template(skill_content)
        return template.render(**context)
    except Exception:
        return skill_content


def load_persona(
    agent_type: str = "developer",
    issue: Optional["Issue"] = None,
    is_takeover: bool = False,
    current_stage: Optional[str] = None,
) -> Optional[str]:
    """Load the persona document for an agent type.

    Args:
        agent_type: Type of agent (developer, manager, reviewer)
        issue: Optional Issue object for Jinja context
        is_takeover: True if agent is taking over mid-workflow
        current_stage: Current dot path for template context

    Returns:
        Persona content as string (rendered with Jinja if issue provided), or None if not found
    """
    from jinja2 import Template
    from agenttree.config import load_config

    # Sync before reading
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=True)

    # Load agent-specific persona
    persona_path = agents_path / "skills" / "roles" / f"{agent_type}.md"
    if not persona_path.exists():
        persona_path = agents_path / "skills" / "overview.md"
        if not persona_path.exists():
            return None

    persona_content = persona_path.read_text()

    # Calculate completed stages (dot paths before current_stage)
    completed_stages: list[str] = []
    if current_stage:
        config = load_config()
        flow_stages = config.get_flow_stage_names(issue.flow if issue else "default")
        parking = config.get_parking_lot_stages()
        for dp in flow_stages:
            if dp == current_stage:
                break
            stage_name, _ = config.parse_stage(dp)
            if stage_name not in parking:
                completed_stages.append(dp)

    # Build Jinja context
    context: dict = {
        "is_takeover": is_takeover,
        "current_stage": current_stage or "",
        "completed_stages": completed_stages,
    }

    if issue:
        issue_dir = get_issue_dir(issue.id)
        context.update({
            "issue_id": issue.id,
            "issue_title": issue.title,
            "issue_dir": str(issue_dir) if issue_dir else "",
            "issue_dir_rel": f"_agenttree/issues/{issue.dir_name}" if issue_dir else "",
        })

    try:
        template = Template(persona_content)
        return template.render(**context)
    except Exception:
        return persona_content


# =============================================================================
# Session Management (for restart detection)
# =============================================================================

class AgentSession(BaseModel):
    """Tracks agent session state for restart detection."""
    session_id: str  # Unique ID per agent start
    issue_id: int
    started_at: str
    last_stage: str  # Dot path (e.g., "explore.define")
    last_advanced_at: str
    oriented: bool = False  # True if agent has been oriented in this session


def get_session_path(issue_id: int | str) -> Optional[Path]:
    """Get path to session file for an issue."""
    issue_dir = get_issue_dir(issue_id)
    if not issue_dir:
        return None
    return issue_dir / ".agent_session.yaml"


def get_session(issue_id: int | str) -> Optional[AgentSession]:
    """Load session state for an issue."""
    session_path = get_session_path(issue_id)
    if not session_path or not session_path.exists():
        return None

    try:
        data = safe_yaml_load(session_path)
        return AgentSession(**data)
    except Exception:
        return None


def create_session(issue_id: int | str) -> AgentSession:
    """Create a new session for an issue."""
    import uuid

    issue = get_issue(issue_id)
    if not issue:
        raise ValueError(f"Issue {issue_id} not found")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session = AgentSession(
        session_id=str(uuid.uuid4())[:8],
        issue_id=issue.id,
        started_at=now,
        last_stage=issue.stage,
        last_advanced_at=now,
        oriented=False,
    )

    save_session(session)
    return session


def save_session(session: AgentSession) -> None:
    """Save session state."""
    session_path = get_session_path(session.issue_id)
    if not session_path:
        log.warning("Could not find issue directory for %s, session not saved", session.issue_id)
        return

    try:
        with open(session_path, "w") as f:
            yaml.dump(session.model_dump(mode="json"), f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        log.warning("Failed to save session for %s: %s", session.issue_id, e)


def update_session_stage(issue_id: str, stage: str) -> None:
    """Update session after stage advancement."""
    session = get_session(issue_id)
    if not session:
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session.last_stage = stage
    session.last_advanced_at = now
    session.oriented = True  # After advancing, agent is oriented
    save_session(session)


def mark_session_oriented(issue_id: str, stage: Optional[str] = None) -> None:
    """Mark that agent has been oriented in this session.

    Also syncs last_stage if provided, so is_restart()
    won't keep detecting a stage mismatch.
    """
    session = get_session(issue_id)
    if not session:
        return

    session.oriented = True
    if stage:
        session.last_stage = stage
    save_session(session)


def is_restart(issue_id: int | str, current_stage: Optional[str] = None) -> bool:
    """Check if agent should re-orient (show instructions without advancing).

    Returns True if:
    - Stage changed externally (e.g., human approval) - detected by comparing
      session.last_stage with current issue stage
    - Session exists but agent hasn't been oriented yet (tmux restart)

    Returns False if:
    - No session exists (fresh start)
    - Session exists, stage matches, and agent has been oriented
    """
    session = get_session(issue_id)
    if not session:
        return False  # No session = fresh start

    # Stage changed externally (e.g., human approval advanced us)
    if current_stage and session.last_stage != current_stage:
        return True

    # Tmux restarted but same stage - use oriented flag
    return not session.oriented


def delete_session(issue_id: int | str) -> None:
    """Delete session file (e.g., when agent is destroyed)."""
    session_path = get_session_path(issue_id)
    if session_path and session_path.exists():
        session_path.unlink()


def get_output_files_after_stage(target_dot_path: str, flow: str = "default") -> list[str]:
    """Get list of output files for stages AFTER the target stage.

    Used by rollback to determine which files need to be archived.

    Args:
        target_dot_path: The dot path being rolled back to (files from this stage are NOT included)
        flow: Flow name to use for stage ordering

    Returns:
        List of output filenames (e.g., ["spec.md", "spec_review.md", "review.md"])

    Raises:
        ValueError: If target_dot_path is not a valid dot path in the flow
    """
    from agenttree.config import load_config

    config = load_config()

    flow_stages = config.get_flow_stage_names(flow)
    if target_dot_path not in flow_stages:
        raise ValueError(f"Unknown stage: {target_dot_path}")

    target_idx = flow_stages.index(target_dot_path)

    # Collect output files from stages after target
    output_files: set[str] = set()
    for dp in flow_stages[target_idx + 1:]:
        output = config.output_for(dp)
        if output:
            output_files.add(output)

    return list(output_files)


def archive_issue_files(issue_id: str, files: list[str]) -> list[str]:
    """Archive output files from an issue directory.

    Moves specified files to an archive/ subdirectory with timestamp prefix
    to avoid collisions when rolling back multiple times.

    Args:
        issue_id: Issue ID
        files: List of filenames to archive (e.g., ["spec.md", "review.md"])

    Returns:
        List of successfully archived file paths (relative to issue dir)
    """
    issue_dir = get_issue_dir(issue_id)
    if not issue_dir:
        raise ValueError(f"Issue {issue_id} not found")

    archive_dir = issue_dir / "archive"
    archive_dir.mkdir(exist_ok=True)

    archived: list[str] = []
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    for filename in files:
        src_path = issue_dir / filename
        if not src_path.exists():
            continue  # Skip files that don't exist

        dest_name = f"{timestamp}-{filename}"
        dest_path = archive_dir / dest_name

        try:
            src_path.rename(dest_path)
            archived.append(f"archive/{dest_name}")
        except OSError as e:
            # Log warning but continue with other files
            log.warning("Could not archive %s: %s", filename, e)

    return archived


def get_issue_context(issue: Issue, include_docs: bool = True) -> dict:
    """Build a complete context dict for an issue.

    This is the single source of truth for issue context, used by:
    - CLI: `agenttree issue show --json/--field`
    - Template rendering in hooks.py and load_skill()

    Args:
        issue: Issue object
        include_docs: If True, load document contents (problem_md, research_md, etc.)

    Returns:
        Dict with all issue fields plus derived fields
    """
    from typing import Any

    # Start with all Issue model fields
    context: dict[str, Any] = issue.model_dump(mode="json")

    # Get issue directory
    issue_dir = get_issue_dir(issue.id)

    # Add derived fields
    context["issue_id"] = issue.id  # Alias for templates
    context["issue_title"] = issue.title  # Alias for templates
    context["issue_dir"] = str(issue_dir) if issue_dir else ""
    context["issue_dir_rel"] = f"_agenttree/issues/{issue.dir_name}" if issue_dir else ""

    # Parse dot path into group and substage for templates
    from agenttree.config import load_config
    cfg = load_config()
    stage_group, substage = cfg.parse_stage(issue.stage)
    context["stage_group"] = stage_group
    context["substage"] = substage or ""

    # Load document contents if requested
    if include_docs and issue_dir:
        doc_names = ["problem.md", "research.md", "spec.md", "spec_review.md", "review.md"]
        for doc_name in doc_names:
            doc_path = issue_dir / doc_name
            var_name = doc_name.replace(".md", "_md").replace("-", "_")
            if doc_path.exists():
                context[var_name] = doc_path.read_text()
            else:
                context[var_name] = ""

    return context
