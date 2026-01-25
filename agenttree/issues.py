"""Issue management for AgentTree.

This module handles CRUD operations for issues stored in _agenttree/issues/.
"""

import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from agenttree.agents_repo import sync_agents_repo


class Priority(str, Enum):
    """Issue priority levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Stage constants for convenience (stages are now config-driven strings)
# Full stage configuration is loaded from .agenttree.yaml via config.py
BACKLOG = "backlog"
DEFINE = "define"
RESEARCH = "research"
PLAN = "plan"
PLAN_ASSESS = "plan_assess"
PLAN_REVISE = "plan_revise"
PLAN_REVIEW = "plan_review"
IMPLEMENT = "implement"
INDEPENDENT_CODE_REVIEW = "independent_code_review"
IMPLEMENTATION_REVIEW = "implementation_review"
ACCEPTED = "accepted"
NOT_DOING = "not_doing"


class HistoryEntry(BaseModel):
    """A single entry in issue history."""
    stage: str
    substage: Optional[str] = None
    timestamp: str
    agent: Optional[int] = None
    type: str = "transition"  # "transition" (normal), "rollback", etc.


class Issue(BaseModel):
    """An issue in the agenttree workflow."""
    id: str
    slug: str
    title: str
    created: str
    updated: str

    stage: str = DEFINE
    substage: Optional[str] = "refine"

    branch: Optional[str] = None
    worktree_dir: Optional[str] = None  # Absolute path to worktree directory

    labels: list[str] = Field(default_factory=list)
    priority: Priority = Priority.MEDIUM

    # Dependencies: list of issue IDs that must be completed (accepted stage) before this issue can start
    dependencies: list[str] = Field(default_factory=list)

    github_issue: Optional[int] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    relevant_url: Optional[str] = None

    history: list[HistoryEntry] = Field(default_factory=list)

    custom_agent_spawned: Optional[str] = None  # Stage name where custom agent was spawned


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

    # Fallback to local path
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
            # Extract number from directory name (e.g., "001-fix-login" -> 1)
            match = re.match(r'^(\d+)-', issue_dir.name)
            if match:
                num = int(match.group(1))
                max_num = max(max_num, num)

    return max_num + 1


def create_issue(
    title: str,
    priority: Priority = Priority.MEDIUM,
    labels: Optional[list[str]] = None,
    stage: str = DEFINE,
    substage: Optional[str] = None,
    problem: Optional[str] = None,
    context: Optional[str] = None,
    solutions: Optional[str] = None,
    dependencies: Optional[list[str]] = None,
) -> Issue:
    """Create a new issue.

    Args:
        title: Issue title
        priority: Issue priority
        labels: Optional list of labels
        stage: Starting stage for the issue (default: DEFINE)
        substage: Starting substage (default: "refine" for define stage)
        problem: Problem statement text (fills problem.md)
        context: Context/background text (fills problem.md)
        solutions: Possible solutions text (fills problem.md)
        dependencies: Optional list of issue IDs that must be completed first

    Returns:
        The created Issue object
    """
    # Default substage for define stage
    if stage == DEFINE and substage is None:
        substage = "refine"
    # Sync before and after writing
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=True)

    issues_path = get_issues_path()
    issues_path.mkdir(parents=True, exist_ok=True)

    # Generate ID and slug
    num = get_next_issue_number()
    issue_id = f"{num:03d}"
    slug = slugify(title)
    dir_name = f"{issue_id}-{slug}"

    # Create issue directory
    issue_dir = issues_path / dir_name
    issue_dir.mkdir(exist_ok=True)

    # Normalize dependencies (ensure they're padded to 3 digits)
    normalized_deps: list[str] = []
    if dependencies:
        for dep in dependencies:
            dep_num = dep.lstrip("0") or "0"
            normalized_deps.append(f"{int(dep_num):03d}")

        # Check for circular dependencies before creating
        cycle = detect_circular_dependency(issue_id, normalized_deps)
        if cycle:
            raise ValueError(
                f"Circular dependency detected: {' -> '.join(cycle)}"
            )

    # Create issue object
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue = Issue(
        id=issue_id,
        slug=slug,
        title=title,
        created=now,
        updated=now,
        stage=stage,
        substage=substage,
        priority=priority,
        labels=labels or [],
        dependencies=normalized_deps,
        history=[
            HistoryEntry(stage=stage, substage=substage, timestamp=now)
        ]
    )

    # Write issue.yaml
    yaml_path = issue_dir / "issue.yaml"
    with open(yaml_path, "w") as f:
        # Use mode="json" to get plain strings for enums
        data = issue.model_dump(mode="json")
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

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

    # Sync after creating issue
    sync_agents_repo(agents_path, pull_only=False, commit_message=f"Create issue {issue_id}: {title}")

    return issue


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
    # Sync before reading (skip for web UI to avoid latency)
    if sync:
        agents_path = get_agenttree_path()
        sync_agents_repo(agents_path, pull_only=True)

    issues_path = get_issues_path()
    if not issues_path.exists():
        return []

    issues = []
    for issue_dir in sorted(issues_path.iterdir()):
        if not issue_dir.is_dir() or issue_dir.name == "archive":
            continue

        yaml_path = issue_dir / "issue.yaml"
        if not yaml_path.exists():
            continue

        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        try:
            issue = Issue(**data)
        except Exception:
            # Skip malformed issues
            continue

        # Apply filters
        if stage and issue.stage != stage:
            continue
        if priority and issue.priority != priority:
            continue

        issues.append(issue)

    return issues


def get_issue(issue_id: str, sync: bool = True) -> Optional[Issue]:
    """Get a single issue by ID.

    Args:
        issue_id: Issue ID (e.g., "001" or "001-fix-login")
        sync: If True, sync with remote before reading (default True for CLI, False for web)

    Returns:
        Issue object or None if not found
    """
    # Sync before reading (skip for web UI to avoid latency)
    if sync:
        agents_path = get_agenttree_path()
        sync_agents_repo(agents_path, pull_only=True)

    issues_path = get_issues_path()
    if not issues_path.exists():
        return None

    # Normalize ID (remove leading zeros for comparison)
    normalized_id = issue_id.lstrip("0") or "0"

    for issue_dir in issues_path.iterdir():
        if not issue_dir.is_dir() or issue_dir.name == "archive":
            continue

        # Check if directory starts with the issue ID
        dir_id = issue_dir.name.split("-")[0].lstrip("0") or "0"
        if dir_id == normalized_id or issue_dir.name == issue_id:
            yaml_path = issue_dir / "issue.yaml"
            if yaml_path.exists():
                with open(yaml_path) as f:
                    data = yaml.safe_load(f)
                return Issue(**data)

    return None


def get_issue_dir(issue_id: str) -> Optional[Path]:
    """Get the directory path for an issue.

    Args:
        issue_id: Issue ID

    Returns:
        Path to issue directory or None
    """
    issues_path = get_issues_path()
    if not issues_path.exists():
        return None

    normalized_id = issue_id.lstrip("0") or "0"

    for issue_dir in issues_path.iterdir():
        if not issue_dir.is_dir() or issue_dir.name == "archive":
            continue

        dir_id = issue_dir.name.split("-")[0].lstrip("0") or "0"
        if dir_id == normalized_id or issue_dir.name == issue_id:
            return issue_dir

    return None


def check_dependencies_met(issue: Issue) -> tuple[bool, list[str]]:
    """Check if all dependencies for an issue are met.

    A dependency is met when the dependent issue is in the ACCEPTED stage.

    Args:
        issue: Issue to check dependencies for

    Returns:
        Tuple of (all_met, unmet_ids) where:
        - all_met: True if all dependencies are met
        - unmet_ids: List of issue IDs that are not yet completed
    """
    if not issue.dependencies:
        return True, []

    unmet = []
    for dep_id in issue.dependencies:
        dep_issue = get_issue(dep_id)
        if dep_issue is None:
            # Dependency doesn't exist - treat as unmet
            unmet.append(dep_id)
        elif dep_issue.stage != ACCEPTED:
            unmet.append(dep_id)

    return len(unmet) == 0, unmet


def remove_dependency(issue_id: str, dep_id: str) -> Optional[Issue]:
    """Remove a dependency from an issue.

    Args:
        issue_id: Issue to remove dependency from
        dep_id: Dependency issue ID to remove

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

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    issue = Issue(**data)

    # Normalize dep_id to match format in dependencies list
    dep_normalized = f"{int(dep_id.lstrip('0') or '0'):03d}"

    # Remove the dependency
    if dep_normalized in issue.dependencies:
        issue.dependencies.remove(dep_normalized)
    elif dep_id in issue.dependencies:
        issue.dependencies.remove(dep_id)

    # Update timestamp
    issue.updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Write back
    with open(yaml_path, "w") as f:
        yaml.dump(issue.model_dump(exclude_none=True), f, default_flow_style=False, sort_keys=False)

    sync_agents_repo(agents_path)
    return issue


def detect_circular_dependency(
    issue_id: str,
    new_dependencies: list[str],
) -> Optional[list[str]]:
    """Detect if adding dependencies would create a circular dependency.

    Uses DFS to detect cycles in the dependency graph.

    Args:
        issue_id: The issue ID to check
        new_dependencies: List of dependency IDs to validate

    Returns:
        List of issue IDs forming the cycle if found, None otherwise
    """
    if not new_dependencies:
        return None

    # Normalize issue ID
    normalized_id = f"{int(issue_id.lstrip('0') or '0'):03d}"

    # Build adjacency list of all existing dependencies
    dep_graph: dict[str, list[str]] = {}
    for issue in list_issues():
        issue_normalized = f"{int(issue.id.lstrip('0') or '0'):03d}"
        dep_graph[issue_normalized] = [
            f"{int(d.lstrip('0') or '0'):03d}" for d in issue.dependencies
        ]

    # Add the new dependencies we're validating
    dep_graph[normalized_id] = [
        f"{int(d.lstrip('0') or '0'):03d}" for d in new_dependencies
    ]

    # DFS to detect cycle starting from issue_id
    visited: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def dfs(node: str) -> Optional[list[str]]:
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

    return dfs(normalized_id)


def get_blocked_issues(completed_issue_id: str) -> list[Issue]:
    """Get all issues in backlog that were waiting on a completed issue.

    Args:
        completed_issue_id: ID of the issue that was just completed

    Returns:
        List of issues that have this issue as a dependency
    """
    # Normalize the ID for comparison
    normalized_id = completed_issue_id.lstrip("0") or "0"

    blocked = []
    for issue in list_issues(stage=BACKLOG):
        # Check if this issue depends on the completed issue
        for dep_id in issue.dependencies:
            dep_normalized = dep_id.lstrip("0") or "0"
            if dep_normalized == normalized_id:
                blocked.append(issue)
                break

    return blocked


def get_dependent_issues(issue_id: str) -> list[Issue]:
    """Get all issues that depend on this issue (any stage).

    Unlike get_blocked_issues which only returns backlog issues,
    this returns ALL issues that have this issue in their dependencies.

    Args:
        issue_id: ID of the issue to find dependents for

    Returns:
        List of issues that depend on this issue
    """
    # Normalize the ID for comparison
    normalized_id = issue_id.lstrip("0") or "0"

    dependents = []
    for issue in list_issues(sync=False):
        # Check if this issue depends on our target
        for dep_id in issue.dependencies:
            dep_normalized = dep_id.lstrip("0") or "0"
            if dep_normalized == normalized_id:
                dependents.append(issue)
                break

    return dependents


def get_ready_issues() -> list[Issue]:
    """Get all issues in backlog that have all dependencies met and can be started.

    Returns:
        List of issues that are ready to start
    """
    ready = []
    for issue in list_issues(stage=BACKLOG):
        if issue.dependencies:
            all_met, _ = check_dependencies_met(issue)
            if all_met:
                ready.append(issue)
        # Issues without dependencies in backlog can also be started
        # but they were likely put there intentionally, so don't auto-start

    return ready


# Stage workflow definitions are now config-driven via .agenttree.yaml
# These compatibility constants are provided for backward compatibility with tests
# but the actual workflow logic uses Config.get_next_stage()

# Legacy compatibility: stage lists now derived from Config
# NOTE: For most use cases, import and use load_config() from agenttree.config
STAGE_ORDER = [
    BACKLOG,
    DEFINE,
    RESEARCH,
    PLAN,
    PLAN_ASSESS,
    PLAN_REVISE,
    PLAN_REVIEW,
    IMPLEMENT,
    IMPLEMENTATION_REVIEW,
    ACCEPTED,
    NOT_DOING,
]

STAGE_SUBSTAGES = {
    DEFINE: ["draft", "refine"],
    RESEARCH: ["explore", "document"],
    PLAN: ["draft", "refine"],
    IMPLEMENT: ["setup", "test", "code", "debug", "code_review", "address_review"],
}

HUMAN_REVIEW_STAGES = {
    PLAN_REVIEW,
    IMPLEMENTATION_REVIEW,
}


def get_next_stage(
    current_stage: str,
    current_substage: Optional[str] = None,
) -> tuple[str, Optional[str], bool]:
    """Calculate the next stage/substage.

    Delegates to Config.get_next_stage() for config-driven workflow.

    Args:
        current_stage: Current stage name (string)
        current_substage: Current substage (if any)

    Returns:
        Tuple of (next_stage, next_substage, is_human_review)
        is_human_review is True if the next stage requires human approval
    """
    from agenttree.config import load_config

    config = load_config()
    return config.get_next_stage(current_stage, current_substage)


def update_issue_stage(
    issue_id: str,
    stage: str,
    substage: Optional[str] = None,
    agent: Optional[int] = None,
) -> Optional[Issue]:
    """Update an issue's stage and substage.

    Args:
        issue_id: Issue ID
        stage: New stage (string)
        substage: New substage (optional)
        agent: Agent number making the change (optional)

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

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    issue = Issue(**data)

    # Update stage
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue.stage = stage
    issue.substage = substage
    issue.updated = now

    # Add history entry
    history_entry = HistoryEntry(
        stage=stage,
        substage=substage,
        timestamp=now,
        agent=agent,
    )
    issue.history.append(history_entry)

    # Write back
    with open(yaml_path, "w") as f:
        data = issue.model_dump(mode="json")
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # Sync after updating stage
    stage_str = stage
    if substage:
        stage_str += f".{substage}"
    sync_agents_repo(agents_path, pull_only=False, commit_message=f"Update issue {issue_id} to stage {stage_str}")

    return issue


def update_issue_metadata(
    issue_id: str,
    pr_number: Optional[int] = None,
    pr_url: Optional[str] = None,
    branch: Optional[str] = None,
    github_issue: Optional[int] = None,
    relevant_url: Optional[str] = None,
    worktree_dir: Optional[str] = None,
    clear_pr: bool = False,
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

    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    issue = Issue(**data)

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
    issue.updated = now

    # Write back
    with open(yaml_path, "w") as f:
        data = issue.model_dump(mode="json")
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # Sync after updating metadata
    sync_agents_repo(agents_path, pull_only=False, commit_message=f"Update issue {issue_id} metadata")

    return issue


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
    stage: str,
    substage: Optional[str] = None,
    issue: Optional["Issue"] = None,
    include_system: bool = False,
) -> Optional[str]:
    """Load skill/instructions for a stage, rendered with Jinja if issue provided.

    Uses Config.skill_path() for resolving skill file locations.
    Convention: skills/{stage}.md or skills/{stage}/{substage}.md

    Args:
        stage: Stage name (string) to load skill for
        substage: Optional substage for more specific skill
        issue: Optional Issue object for Jinja context
        include_system: If True, prepend AGENTS.md system prompt (for first stage)

    Returns:
        Skill content as string (rendered if issue provided), or None if not found
    """
    from jinja2 import Template
    from agenttree.config import load_config

    # Sync before reading
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=True)

    config = load_config()

    # Get skill path from config
    skill_rel_path = config.skill_path(stage, substage)
    skill_path = agents_path / skill_rel_path

    skill_content = None

    # Try the config-specified path first
    if skill_path.exists():
        skill_content = skill_path.read_text()
    else:
        # Try legacy naming convention: {stage}-{substage}.md
        skills_dir = agents_path / "skills"
        if substage:
            legacy_path = skills_dir / f"{stage}-{substage}.md"
            if legacy_path.exists():
                skill_content = legacy_path.read_text()

        # Fall back to stage skill without substage
        if skill_content is None:
            stage_skill = skills_dir / f"{stage}.md"
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

    # Build Jinja context
    issue_dir = get_issue_dir(issue.id)
    context = {
        "issue_id": issue.id,
        "issue_title": issue.title,
        "issue_dir": str(issue_dir) if issue_dir else "",
        "issue_dir_rel": f"_agenttree/issues/{issue.id}-{issue.slug}" if issue_dir else "",
        "stage": stage,
        "substage": substage or "",
    }

    # Load document contents if they exist
    if issue_dir:
        for doc_name in ["problem.md", "research.md", "spec.md", "spec_review.md", "review.md"]:
            doc_path = issue_dir / doc_name
            var_name = doc_name.replace(".md", "_md").replace("-", "_")
            if doc_path.exists():
                context[var_name] = doc_path.read_text()
            else:
                context[var_name] = ""

    # Load project-level review checklist if it exists (for project-specific patterns)
    # Look in skills directory to keep all skill-related files together
    project_review_path = agents_path / "skills" / "project_review.md"
    if project_review_path.exists():
        context["project_review_md"] = project_review_path.read_text()
    else:
        context["project_review_md"] = ""

    # Inject command outputs for referenced commands
    # Commands run in worktree directory if available, otherwise issue directory
    from agenttree.commands import get_referenced_commands, get_command_output

    if config.commands:
        # Determine working directory for commands
        cwd = None
        if issue.worktree_dir:
            cwd = Path(issue.worktree_dir)
        elif issue_dir:
            cwd = issue_dir

        # Find commands referenced in the template
        referenced = get_referenced_commands(skill_content, config.commands)

        for cmd_name in referenced:
            # Don't overwrite built-in context variables
            if cmd_name not in context:
                context[cmd_name] = get_command_output(
                    config.commands, cmd_name, cwd=cwd
                )

    # Render with Jinja
    try:
        template = Template(skill_content)
        return template.render(**context)
    except Exception:
        # If rendering fails, return raw content
        return skill_content


def load_overview(
    issue: Optional["Issue"] = None,
    is_takeover: bool = False,
    current_stage: Optional[str] = None,
    current_substage: Optional[str] = None,
) -> Optional[str]:
    """Load the overview document with takeover context for agents.

    Used when an agent restarts to provide context about the AgentTree workflow.

    Args:
        issue: Optional Issue object for Jinja context
        is_takeover: True if agent is taking over mid-workflow (not from backlog/define)
        current_stage: Current stage name for template context
        current_substage: Current substage name for template context

    Returns:
        Overview content as string (rendered with Jinja if issue provided), or None if not found
    """
    from jinja2 import Template

    # Sync before reading
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=True)

    overview_path = agents_path / "skills" / "overview.md"
    if not overview_path.exists():
        return None

    overview_content = overview_path.read_text()

    # Calculate completed stages (stages before current_stage)
    completed_stages: list[str] = []
    if current_stage:
        for stage in STAGE_ORDER:
            if stage == current_stage:
                break
            # Skip backlog and terminal stages
            if stage not in (BACKLOG, ACCEPTED, NOT_DOING):
                completed_stages.append(stage)

    # Build Jinja context
    context = {
        "is_takeover": is_takeover,
        "current_stage": current_stage or "",
        "current_substage": current_substage or "",
        "completed_stages": completed_stages,
    }

    # Add issue context if available
    if issue:
        issue_dir = get_issue_dir(issue.id)
        context.update({
            "issue_id": issue.id,
            "issue_title": issue.title,
            "issue_dir": str(issue_dir) if issue_dir else "",
            "issue_dir_rel": f"_agenttree/issues/{issue.id}-{issue.slug}" if issue_dir else "",
        })

    # Render with Jinja
    try:
        template = Template(overview_content)
        return template.render(**context)
    except Exception:
        # If rendering fails, return raw content
        return overview_content


# =============================================================================
# Session Management (for restart detection)
# =============================================================================

class AgentSession(BaseModel):
    """Tracks agent session state for restart detection."""
    session_id: str  # Unique ID per agent start
    issue_id: str
    started_at: str
    last_stage: str
    last_substage: Optional[str] = None
    last_advanced_at: str
    oriented: bool = False  # True if agent has been oriented in this session


def get_session_path(issue_id: str) -> Optional[Path]:
    """Get path to session file for an issue."""
    issue_dir = get_issue_dir(issue_id)
    if not issue_dir:
        return None
    return issue_dir / ".agent_session.yaml"


def get_session(issue_id: str) -> Optional[AgentSession]:
    """Load session state for an issue."""
    session_path = get_session_path(issue_id)
    if not session_path or not session_path.exists():
        return None

    try:
        with open(session_path) as f:
            data = yaml.safe_load(f)
            return AgentSession(**data)
    except Exception:
        return None


def create_session(issue_id: str) -> AgentSession:
    """Create a new session for an issue."""
    import uuid

    issue = get_issue(issue_id)
    if not issue:
        raise ValueError(f"Issue {issue_id} not found")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session = AgentSession(
        session_id=str(uuid.uuid4())[:8],
        issue_id=issue_id,
        started_at=now,
        last_stage=issue.stage,
        last_substage=issue.substage,
        last_advanced_at=now,
        oriented=False,
    )

    save_session(session)
    return session


def save_session(session: AgentSession) -> None:
    """Save session state."""
    session_path = get_session_path(session.issue_id)
    if not session_path:
        print(f"Warning: Could not find issue directory for {session.issue_id}, session not saved")
        return

    try:
        with open(session_path, "w") as f:
            yaml.dump(session.model_dump(mode="json"), f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        print(f"Warning: Failed to save session for {session.issue_id}: {e}")


def update_session_stage(issue_id: str, stage: str, substage: Optional[str] = None) -> None:
    """Update session after stage advancement."""
    session = get_session(issue_id)
    if not session:
        return

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    session.last_stage = stage
    session.last_substage = substage
    session.last_advanced_at = now
    session.oriented = True  # After advancing, agent is oriented
    save_session(session)


def mark_session_oriented(issue_id: str, stage: Optional[str] = None, substage: Optional[str] = None) -> None:
    """Mark that agent has been oriented in this session.

    Also syncs last_stage/last_substage if provided, so is_restart()
    won't keep detecting a stage mismatch.
    """
    session = get_session(issue_id)
    if not session:
        return

    session.oriented = True
    if stage:
        session.last_stage = stage
    if substage is not None:
        session.last_substage = substage
    save_session(session)


def is_restart(issue_id: str, current_stage: Optional[str] = None, current_substage: Optional[str] = None) -> bool:
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
    # This handles the case where controller moved us to a new stage
    if current_stage and session.last_stage != current_stage:
        return True
    if current_substage is not None and session.last_substage != current_substage:
        return True

    # Tmux restarted but same stage - use oriented flag
    return not session.oriented


def delete_session(issue_id: str) -> None:
    """Delete session file (e.g., when agent is destroyed)."""
    session_path = get_session_path(issue_id)
    if session_path and session_path.exists():
        session_path.unlink()


def get_output_files_after_stage(target_stage: str) -> list[str]:
    """Get list of output files for stages AFTER the target stage.

    Used by rollback to determine which files need to be archived.

    Args:
        target_stage: The stage being rolled back to (files from this stage are NOT included)

    Returns:
        List of output filenames (e.g., ["spec.md", "spec_review.md", "review.md"])

    Raises:
        ValueError: If target_stage is not a valid stage name
    """
    from agenttree.config import load_config

    config = load_config()

    # Find target stage index
    stage_names = [s.name for s in config.stages]
    if target_stage not in stage_names:
        raise ValueError(f"Unknown stage: {target_stage}")

    target_idx = stage_names.index(target_stage)

    # Collect output files from stages after target
    output_files: set[str] = set()
    for stage in config.stages[target_idx + 1 :]:
        # Stage-level output
        if stage.output:
            output_files.add(stage.output)

        # Substage outputs
        for substage in stage.substages.values():
            if substage.output:
                output_files.add(substage.output)

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
            print(f"Warning: Could not archive {filename}: {e}")

    return archived
