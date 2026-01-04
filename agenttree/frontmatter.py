"""Frontmatter utilities for AgentTree.

Handles YAML frontmatter in markdown files:
- Creating frontmatter blocks
- Parsing frontmatter from existing files
- Getting git context for metadata
- Validating frontmatter schemas
"""

import subprocess
import yaml
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from datetime import datetime


def create_frontmatter(data: Dict[str, Any]) -> str:
    """Create YAML frontmatter block.

    Args:
        data: Dictionary of frontmatter fields

    Returns:
        YAML frontmatter block with delimiters

    Example:
        >>> create_frontmatter({"title": "Test", "version": 1})
        '---\\ntitle: Test\\nversion: 1\\n---\\n\\n'
    """
    yaml_content = yaml.dump(data, default_flow_style=False, sort_keys=False)
    return f"---\n{yaml_content}---\n\n"


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse frontmatter and content from markdown.

    Args:
        content: Full markdown file content

    Returns:
        Tuple of (frontmatter dict, markdown content)

    Example:
        >>> content = "---\\ntitle: Test\\n---\\n\\n# Content"
        >>> fm, md = parse_frontmatter(content)
        >>> fm['title']
        'Test'
        >>> md
        '# Content'
    """
    if not content.startswith("---"):
        return {}, content

    try:
        # Split on --- delimiters
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        frontmatter = yaml.safe_load(parts[1])
        markdown = parts[2].strip()

        return frontmatter or {}, markdown
    except yaml.YAMLError:
        # Invalid YAML, return empty frontmatter
        return {}, content


def get_git_context(repo_path: Path) -> Dict[str, Any]:
    """Get current git context for frontmatter.

    Args:
        repo_path: Path to git repository

    Returns:
        Dictionary with repo_url, starting_commit, starting_branch

    Example:
        >>> ctx = get_git_context(Path.cwd())
        >>> 'starting_commit' in ctx
        True
    """
    try:
        # Get current commit hash
        current_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()

        # Get current branch name
        current_branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()

        # Get remote URL
        repo_url = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()

        # Convert git@github.com:user/repo.git to https://github.com/user/repo
        if repo_url.startswith("git@"):
            repo_url = repo_url.replace(":", "/").replace("git@", "https://")
        if repo_url.endswith(".git"):
            repo_url = repo_url[:-4]

        return {
            "repo_url": repo_url,
            "starting_commit": current_commit,
            "starting_branch": current_branch,
        }
    except subprocess.CalledProcessError:
        # Git command failed, return minimal context
        return {
            "repo_url": None,
            "starting_commit": None,
            "starting_branch": None,
        }


def get_commits_since(repo_path: Path, since_commit: str) -> list[Dict[str, str]]:
    """Get list of commits since a given commit.

    Args:
        repo_path: Path to git repository
        since_commit: Commit hash to start from

    Returns:
        List of dicts with hash, message, timestamp

    Example:
        >>> commits = get_commits_since(Path.cwd(), "abc123")
        >>> commits[0]['hash']
        'def456'
    """
    try:
        # Get commits since starting commit
        result = subprocess.run(
            [
                "git", "log",
                f"{since_commit}..HEAD",
                "--pretty=format:%H|%s|%aI"  # hash|subject|ISO timestamp
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({
                    "hash": parts[0],
                    "message": parts[1],
                    "timestamp": parts[2]
                })

        return commits
    except subprocess.CalledProcessError:
        return []


def update_frontmatter_field(file_path: Path, field: str, value: Any) -> None:
    """Update a single field in frontmatter.

    Args:
        file_path: Path to markdown file
        field: Field name to update
        value: New value for field

    Example:
        >>> update_frontmatter_field(Path("task.md"), "status", "completed")
    """
    content = file_path.read_text()
    frontmatter, markdown = parse_frontmatter(content)

    # Update field
    frontmatter[field] = value

    # Write back
    new_content = create_frontmatter(frontmatter) + markdown
    file_path.write_text(new_content)


def add_frontmatter_fields(file_path: Path, fields: Dict[str, Any]) -> None:
    """Add multiple fields to frontmatter.

    Args:
        file_path: Path to markdown file
        fields: Dictionary of fields to add/update

    Example:
        >>> add_frontmatter_fields(Path("task.md"), {"pr_number": 50, "status": "completed"})
    """
    content = file_path.read_text()
    frontmatter, markdown = parse_frontmatter(content)

    # Update fields
    frontmatter.update(fields)

    # Write back
    new_content = create_frontmatter(frontmatter) + markdown
    file_path.write_text(new_content)


def utc_now() -> str:
    """Get current UTC timestamp in ISO 8601 format.

    Returns:
        ISO 8601 timestamp string with 'Z' suffix

    Example:
        >>> utc_now()
        '2026-01-04T10:30:00Z'
    """
    return datetime.utcnow().isoformat() + "Z"


def validate_required_fields(frontmatter: Dict[str, Any], required: list[str]) -> list[str]:
    """Validate that required fields are present.

    Args:
        frontmatter: Frontmatter dictionary
        required: List of required field names

    Returns:
        List of missing field names (empty if all present)

    Example:
        >>> validate_required_fields({"title": "Test"}, ["title", "version"])
        ['version']
    """
    missing = []
    for field in required:
        if field not in frontmatter or frontmatter[field] is None:
            missing.append(field)
    return missing
