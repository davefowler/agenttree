"""Integration test fixtures for AgentTree workflow testing.

These fixtures create real git repositories and agenttree structures
for end-to-end workflow testing.
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Generator, Optional
from unittest.mock import MagicMock, patch

import pytest
import yaml


@pytest.fixture
def git_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a real git repository for testing.

    Initializes a git repo with an initial commit.
    """
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path, check=True, capture_output=True
    )

    # Create initial commit
    (repo_path / "README.md").write_text("# Test Project\n")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path, check=True, capture_output=True
    )

    yield repo_path


@pytest.fixture
def agenttree_config() -> dict[str, Any]:
    """Minimal agenttree configuration for testing.

    Contains all stages with essential hooks for workflow testing.
    """
    return {
        "default_tool": "claude",
        "default_model": "opus",
        "port_range": "9001-9099",
        "project": "test-project",
        "worktrees_dir": ".worktrees",
        "test_commands": ["echo 'tests pass'"],
        "lint_commands": ["echo 'lint pass'"],
        "tools": {
            "claude": {
                "command": "claude",
                "startup_prompt": "Read TASK.md"
            }
        },
        "stages": [
            {"name": "backlog"},
            {
                "name": "define",
                "output": "problem.md",
                "pre_completion": [
                    {"section_check": {"file": "problem.md", "section": "Context", "expect": "not_empty"}}
                ],
                "substages": {"refine": {}}
            },
            {
                "name": "research",
                "output": "research.md",
                "post_start": [
                    {"create_file": {"template": "research.md", "dest": "research.md"}}
                ],
                "pre_completion": [
                    {"section_check": {"file": "research.md", "section": "Relevant Files", "expect": "not_empty"}}
                ],
                "substages": {"explore": {}, "document": {}}
            },
            {
                "name": "plan",
                "output": "spec.md",
                "post_start": [
                    {"create_file": {"template": "spec.md", "dest": "spec.md"}}
                ],
                "pre_completion": [
                    {"section_check": {"file": "spec.md", "section": "Approach", "expect": "not_empty"}},
                    {"has_list_items": {"file": "spec.md", "section": "Files to Modify"}},
                    {"has_list_items": {"file": "spec.md", "section": "Implementation Steps"}},
                    {"section_check": {"file": "spec.md", "section": "Test Plan", "expect": "not_empty"}}
                ],
                "substages": {"draft": {}, "refine": {}}
            },
            {
                "name": "plan_assess",
                "output": "spec_review.md",
                "post_start": [
                    {"create_file": {"template": "spec_review.md", "dest": "spec_review.md"}}
                ],
                "pre_completion": [
                    {"section_check": {"file": "spec_review.md", "section": "Assessment Summary", "expect": "not_empty"}}
                ]
            },
            {"name": "plan_revise", "output": "spec.md"},
            {
                "name": "plan_review",
                "human_review": True,
                "pre_completion": [
                    {"file_exists": "spec.md"},
                    {"section_check": {"file": "spec.md", "section": "Approach", "expect": "not_empty"}}
                ]
            },
            {
                "name": "implement",
                "substages": {
                    "setup": {},
                    "code": {},
                    "code_review": {
                        "output": "review.md",
                        "post_start": [
                            {"create_file": {"template": "review.md", "dest": "review.md"}}
                        ],
                        "pre_completion": [
                            {"section_check": {"file": "review.md", "section": "Self-Review Checklist", "expect": "all_checked"}}
                        ]
                    },
                    "address_review": {},
                    "wrapup": {
                        "pre_completion": [
                            {"file_exists": "review.md"},
                            {"field_check": {"file": "review.md", "path": "scores.average", "min": 7}}
                        ]
                    },
                    "feedback": {
                        "pre_completion": [
                            {"has_commits": {}},
                            {"file_exists": "review.md"},
                            {"section_check": {"file": "review.md", "section": "Critical Issues", "expect": "empty"}}
                        ]
                    }
                }
            },
            {
                "name": "implementation_review",
                "human_review": True,
                "host": "controller",
                "post_start": [{"create_pr": {}}],
                "pre_completion": [{"pr_approved": {}}]
            },
            {
                "name": "knowledge_base",
                "host": "agent",
                "skill": "knowledge_base.md"
            },
            {
                "name": "accepted",
                "is_parking_lot": True,
                "host": "controller",
                "post_start": [
                    {"merge_pr": {}},
                    {"cleanup_agent": {}},
                    {"start_blocked_issues": {}}
                ]
            },
            {"name": "not_doing", "is_parking_lot": True}
        ]
    }


@pytest.fixture
def workflow_repo(git_repo: Path, agenttree_config: dict[str, Any]) -> Path:
    """Create a complete agenttree project structure for workflow testing.

    Creates:
    - Real git repo with initial commit
    - .agenttree.yaml with standard config
    - _agenttree/ directory structure
    - templates/ directory with basic templates
    """
    # Write config
    config_path = git_repo / ".agenttree.yaml"
    with open(config_path, "w") as f:
        yaml.dump(agenttree_config, f, default_flow_style=False, sort_keys=False)

    # Create _agenttree directory structure
    agenttree_dir = git_repo / "_agenttree"
    (agenttree_dir / "issues").mkdir(parents=True)
    (agenttree_dir / "templates").mkdir(parents=True)
    (agenttree_dir / "skills").mkdir(parents=True)

    # Create minimal templates
    templates = {
        "problem.md": "# Problem\n\n## Context\n\n<!-- Add context here -->\n\n## Possible Solutions\n\n- Solution 1\n",
        "research.md": "# Research\n\n## Relevant Files\n\n<!-- Add files here -->\n\n## Existing Patterns\n\n<!-- Add patterns -->\n",
        "spec.md": "# Specification\n\n## Approach\n\n<!-- Describe approach -->\n\n## Files to Modify\n\n- file1.py\n\n## Implementation Steps\n\n1. Step 1\n\n## Test Plan\n\nTest plan here.\n",
        "spec_review.md": "# Spec Review\n\n## Assessment Summary\n\n<!-- Summary here -->\n",
        "review.md": """# Code Review

```yaml
scores:
  correctness: 8
  completeness: 8
  average: 8
```

## Overview

Review overview here.

## Self-Review Checklist

- [x] Code compiles
- [x] Tests pass
- [x] No obvious bugs

## Critical Issues

<!-- None -->
""",
        "feedback.md": "# Feedback\n\nFeedback notes here.\n"
    }

    for name, content in templates.items():
        (agenttree_dir / "templates" / name).write_text(content)

    # Commit the agenttree setup
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Add agenttree structure"],
        cwd=git_repo, check=True, capture_output=True
    )

    return git_repo


@pytest.fixture
def mock_github() -> Generator[MagicMock, None, None]:
    """Mock all GitHub API calls.

    Provides a mock that tracks:
    - PR creation calls
    - PR approval calls
    - PR merge calls
    - PR status queries
    """
    mock = MagicMock()
    mock.created_prs = []
    mock.approved_prs = []
    mock.merged_prs = []
    mock.pr_states = {}

    def create_pr(title: str, body: str = "", **kwargs: Any) -> int:
        pr_num = len(mock.created_prs) + 1
        mock.created_prs.append({"number": pr_num, "title": title, "body": body})
        mock.pr_states[pr_num] = {"merged": False, "approved": False, "author": "test-user"}
        return pr_num

    def approve_pr(pr_number: int) -> bool:
        if pr_number in mock.pr_states:
            mock.approved_prs.append(pr_number)
            mock.pr_states[pr_number]["approved"] = True
            return True
        return False

    def merge_pr(pr_number: int) -> bool:
        if pr_number in mock.pr_states:
            mock.merged_prs.append(pr_number)
            mock.pr_states[pr_number]["merged"] = True
            return True
        return False

    def is_pr_approved(pr_number: int) -> bool:
        return mock.pr_states.get(pr_number, {}).get("approved", False)

    def is_pr_merged(pr_number: int) -> bool:
        return mock.pr_states.get(pr_number, {}).get("merged", False)

    mock.create_pr = create_pr
    mock.approve_pr = approve_pr
    mock.merge_pr = merge_pr
    mock.is_pr_approved = is_pr_approved
    mock.is_pr_merged = is_pr_merged

    yield mock


@pytest.fixture
def mock_container() -> Generator[MagicMock, None, None]:
    """Mock container/tmux operations.

    Simulates agent execution without actual containers.
    """
    mock = MagicMock()
    mock.running_agents = {}
    mock.sent_messages = []

    def start_agent(issue_id: str, worktree_path: Path) -> int:
        agent_num = len(mock.running_agents) + 1
        mock.running_agents[agent_num] = {
            "issue_id": issue_id,
            "worktree_path": worktree_path,
            "running": True
        }
        return agent_num

    def stop_agent(agent_num: int) -> bool:
        if agent_num in mock.running_agents:
            mock.running_agents[agent_num]["running"] = False
            return True
        return False

    def send_message(agent_num: int, message: str) -> bool:
        if agent_num in mock.running_agents and mock.running_agents[agent_num]["running"]:
            mock.sent_messages.append({"agent": agent_num, "message": message})
            return True
        return False

    def is_agent_running(agent_num: int) -> bool:
        return mock.running_agents.get(agent_num, {}).get("running", False)

    mock.start_agent = start_agent
    mock.stop_agent = stop_agent
    mock.send_message = send_message
    mock.is_agent_running = is_agent_running

    yield mock


@pytest.fixture
def mock_sync() -> Generator[MagicMock, None, None]:
    """Mock sync_agents_repo to avoid remote operations.

    Returns True to indicate sync succeeded without actually syncing.
    """
    with patch("agenttree.issues.sync_agents_repo") as mock:
        mock.return_value = True
        yield mock


@pytest.fixture
def mock_git_push() -> Generator[MagicMock, None, None]:
    """Mock git push operations to avoid remote operations."""
    with patch("subprocess.run") as mock:
        original_run = subprocess.run.__wrapped__ if hasattr(subprocess.run, "__wrapped__") else None

        def selective_mock(cmd, *args, **kwargs):
            # Only mock push commands
            if isinstance(cmd, list) and "push" in cmd:
                result = MagicMock()
                result.returncode = 0
                result.stdout = b""
                result.stderr = b""
                return result
            # For non-push commands, call the real function
            # This requires us to import subprocess fresh
            import subprocess as sp
            return sp.run(cmd, *args, **kwargs)

        # Don't actually mock - we need real git for most operations
        yield mock


@pytest.fixture
def workflow_issue(workflow_repo: Path, mock_sync: MagicMock) -> dict[str, Any]:
    """Create a test issue ready for workflow testing.

    Returns dict with issue info including id, path, and worktree.
    """
    from agenttree.issues import create_issue, get_issue_dir

    # Patch the agenttree path to use our test repo
    with patch("agenttree.issues.get_agenttree_path", return_value=workflow_repo / "_agenttree"):
        with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
            issue = create_issue(
                title="Test Issue for Integration",
                description="This is a test issue for integration testing."
            )

            issue_dir = workflow_repo / "_agenttree" / "issues" / f"{issue.id}-{issue.slug}"

            return {
                "id": issue.id,
                "slug": issue.slug,
                "issue": issue,
                "issue_dir": issue_dir,
                "repo_path": workflow_repo,
                "agenttree_path": workflow_repo / "_agenttree"
            }


class WorkflowTestContext:
    """Context manager for workflow testing with proper patching."""

    def __init__(self, repo_path: Path, mock_github: MagicMock, mock_container: MagicMock):
        self.repo_path = repo_path
        self.agenttree_path = repo_path / "_agenttree"
        self.config_path = repo_path / ".agenttree.yaml"
        self.mock_github = mock_github
        self.mock_container = mock_container
        self.patches = []

    def __enter__(self) -> "WorkflowTestContext":
        # Patch agenttree path lookups
        self.patches.append(
            patch("agenttree.issues.get_agenttree_path", return_value=self.agenttree_path)
        )
        # Note: config.load_config uses find_config_file internally
        # Patch sync to avoid remote operations
        self.patches.append(
            patch("agenttree.issues.sync_agents_repo", return_value=True)
        )
        self.patches.append(
            patch("agenttree.agents_repo.sync_agents_repo", return_value=True)
        )
        # Patch GitHub operations
        self.patches.append(
            patch("agenttree.hooks.create_pull_request", side_effect=lambda *a, **k: self.mock_github.create_pr(*a, **k))
        )
        self.patches.append(
            patch("agenttree.hooks.get_pr_approval_status", side_effect=lambda pr: (self.mock_github.is_pr_approved(pr), None))
        )
        self.patches.append(
            patch("agenttree.github.merge_pr", side_effect=lambda pr, **k: self.mock_github.merge_pr(pr))
        )

        for p in self.patches:
            p.start()

        return self

    def __exit__(self, *args: Any) -> None:
        for p in self.patches:
            p.stop()


@pytest.fixture
def workflow_context(
    workflow_repo: Path,
    mock_github: MagicMock,
    mock_container: MagicMock
) -> Generator[WorkflowTestContext, None, None]:
    """Provide a workflow test context with all necessary mocking."""
    ctx = WorkflowTestContext(workflow_repo, mock_github, mock_container)
    with ctx:
        yield ctx
