"""Issue management for AgentTree.

This module handles CRUD operations for issues stored in .agenttrees/issues/.
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
PROBLEM_REVIEW = "problem_review"
RESEARCH = "research"
PLAN = "plan"
PLAN_ASSESS = "plan_assess"
PLAN_REVISE = "plan_revise"
PLAN_REVIEW = "plan_review"
IMPLEMENT = "implement"
IMPLEMENTATION_REVIEW = "implementation_review"
ACCEPTED = "accepted"
NOT_DOING = "not_doing"


class HistoryEntry(BaseModel):
    """A single entry in issue history."""
    stage: str
    substage: Optional[str] = None
    timestamp: str
    agent: Optional[int] = None


class Issue(BaseModel):
    """An issue in the agenttree workflow."""
    id: str
    slug: str
    title: str
    created: str
    updated: str

    stage: str = BACKLOG
    substage: Optional[str] = None

    assigned_agent: Optional[int] = None
    branch: Optional[str] = None

    labels: list[str] = Field(default_factory=list)
    priority: Priority = Priority.MEDIUM

    github_issue: Optional[int] = None
    pr_number: Optional[int] = None
    pr_url: Optional[str] = None
    relevant_url: Optional[str] = None

    history: list[HistoryEntry] = Field(default_factory=list)


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


def get_agenttrees_path() -> Path:
    """Get the path to .agenttrees directory."""
    return Path.cwd() / ".agenttrees"


def get_issues_path() -> Path:
    """Get the path to issues directory."""
    return get_agenttrees_path() / "issues"


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
    stage: str = BACKLOG,
    problem: Optional[str] = None,
    context: Optional[str] = None,
    solutions: Optional[str] = None,
) -> Issue:
    """Create a new issue.

    Args:
        title: Issue title
        priority: Issue priority
        labels: Optional list of labels
        stage: Starting stage for the issue (default: BACKLOG)
        problem: Problem statement text (fills problem.md)
        context: Context/background text (fills problem.md)
        solutions: Possible solutions text (fills problem.md)

    Returns:
        The created Issue object
    """
    # Sync before and after writing
    agents_path = get_agenttrees_path()
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

    # Create issue object
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue = Issue(
        id=issue_id,
        slug=slug,
        title=title,
        created=now,
        updated=now,
        stage=stage,
        priority=priority,
        labels=labels or [],
        history=[
            HistoryEntry(stage=stage, timestamp=now)
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
        template_path = get_agenttrees_path() / "templates" / "problem.md"
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
    assigned_agent: Optional[int] = None,
) -> list[Issue]:
    """List issues, optionally filtered.

    Args:
        stage: Filter by stage
        priority: Filter by priority
        assigned_agent: Filter by assigned agent

    Returns:
        List of Issue objects
    """
    # Sync before reading
    agents_path = get_agenttrees_path()
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
        if assigned_agent is not None and issue.assigned_agent != assigned_agent:
            continue

        issues.append(issue)

    return issues


def get_issue(issue_id: str) -> Optional[Issue]:
    """Get a single issue by ID.

    Args:
        issue_id: Issue ID (e.g., "001" or "001-fix-login")

    Returns:
        Issue object or None if not found
    """
    # Sync before reading
    agents_path = get_agenttrees_path()
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


# Stage workflow definitions are now config-driven via .agenttree.yaml
# These compatibility constants are provided for backward compatibility with tests
# but the actual workflow logic uses Config.get_next_stage()

# Legacy compatibility: stage lists now derived from Config
# NOTE: For most use cases, import and use load_config() from agenttree.config
STAGE_ORDER = [
    BACKLOG,
    DEFINE,
    PROBLEM_REVIEW,
    RESEARCH,
    PLAN,
    PLAN_ASSESS,
    PLAN_REVISE,
    PLAN_REVIEW,
    IMPLEMENT,
    IMPLEMENTATION_REVIEW,
    ACCEPTED,
]

STAGE_SUBSTAGES = {
    DEFINE: ["draft", "refine"],
    RESEARCH: ["explore", "document"],
    PLAN: ["draft", "refine"],
    IMPLEMENT: ["setup", "test", "code", "debug", "code_review", "address_review"],
}

HUMAN_REVIEW_STAGES = {
    PROBLEM_REVIEW,
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
    agents_path = get_agenttrees_path()
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


def assign_agent(issue_id: str, agent_num: int) -> Optional[Issue]:
    """Assign an agent to an issue.

    Args:
        issue_id: Issue ID
        agent_num: Agent number to assign

    Returns:
        Updated Issue object or None if not found
    """
    # Sync before and after writing
    agents_path = get_agenttrees_path()
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

    # Update assignment
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    issue.assigned_agent = agent_num
    issue.updated = now

    # Write back
    with open(yaml_path, "w") as f:
        data = issue.model_dump(mode="json")
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # Sync after assigning agent
    sync_agents_repo(agents_path, pull_only=False, commit_message=f"Assign agent {agent_num} to issue {issue_id}")

    return issue


def update_issue_metadata(
    issue_id: str,
    pr_number: Optional[int] = None,
    pr_url: Optional[str] = None,
    branch: Optional[str] = None,
    github_issue: Optional[int] = None,
    relevant_url: Optional[str] = None,
) -> Optional[Issue]:
    """Update metadata fields on an issue.

    Args:
        issue_id: Issue ID
        pr_number: PR number (optional)
        pr_url: PR URL (optional)
        branch: Branch name (optional)
        github_issue: GitHub issue number (optional)
        relevant_url: Relevant URL (optional)

    Returns:
        Updated Issue object or None if not found
    """
    # Sync before and after writing
    agents_path = get_agenttrees_path()
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
    agents_path = get_agenttrees_path()
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
        "issue_dir_rel": f".agenttrees/issues/{issue.id}-{issue.slug}" if issue_dir else "",
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

    # Render with Jinja
    try:
        template = Template(skill_content)
        return template.render(**context)
    except Exception:
        # If rendering fails, return raw content
        return skill_content
