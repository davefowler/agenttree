"""Tests for agents repository management."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from agenttree.agents_repo import AgentsRepository, slugify


@pytest.fixture
def project_path(tmp_path):
    """Create a temporary repository path."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


@pytest.fixture
def agents_repo(project_path):
    """Create an AgentsRepository instance."""
    return AgentsRepository(project_path)


class TestAgentsRepository:
    """Tests for AgentsRepository class."""

    def test_init(self, project_path):
        """Test AgentsRepository initialization."""
        agents_repo = AgentsRepository(project_path)
        assert agents_repo.project_path == project_path
        assert agents_repo.project_name == "test-repo"
        assert agents_repo.agents_path == project_path / ".agenttrees"

    def test_ensure_repo_already_exists(self, agents_repo):
        """Test ensure_repo when agents/ directory already exists."""
        agents_repo.agents_path.mkdir()
        (agents_repo.agents_path / ".git").mkdir()

        with patch.object(agents_repo, '_ensure_gh_cli') as mock_gh:
            with patch.object(agents_repo, '_create_github_repo') as mock_create:
                with patch.object(agents_repo, '_clone_repo') as mock_clone:
                    agents_repo.ensure_repo()

                    # Should not try to create or clone
                    mock_gh.assert_not_called()
                    mock_create.assert_not_called()
                    mock_clone.assert_not_called()

    def test_ensure_gh_cli_success(self, agents_repo):
        """Test _ensure_gh_cli when gh is available and authenticated."""
        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", return_value=Mock(returncode=0)):
                # Should not raise
                agents_repo._ensure_gh_cli()

    def test_ensure_gh_cli_not_installed(self, agents_repo):
        """Test _ensure_gh_cli when gh is not installed."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(RuntimeError, match="GitHub CLI.*not found"):
                agents_repo._ensure_gh_cli()

    def test_ensure_gh_cli_not_authenticated(self, agents_repo):
        """Test _ensure_gh_cli when gh is not authenticated."""
        with patch("shutil.which", return_value="/usr/bin/gh"):
            with patch("subprocess.run", return_value=Mock(returncode=1)):
                with pytest.raises(RuntimeError, match="Not authenticated"):
                    agents_repo._ensure_gh_cli()

    def test_create_spec_file(self, agents_repo, tmp_path):
        """Test create_spec_file creates spec from issue."""
        agents_repo.agents_path = tmp_path / "agents"
        agents_repo.agents_path.mkdir()
        (agents_repo.agents_path / "specs" / "features").mkdir(parents=True)

        with patch.object(agents_repo, '_commit'):
            agents_repo.create_spec_file(
                issue_num=42,
                issue_title="Add dark mode",
                issue_body="Users want dark mode support",
                issue_url="https://github.com/user/repo/issues/42"
            )

        spec_file = agents_repo.agents_path / "specs" / "features" / "issue-42.md"
        assert spec_file.exists()

        content = spec_file.read_text()
        assert "# Add dark mode" in content
        assert "[#42](https://github.com/user/repo/issues/42)" in content
        assert "Users want dark mode support" in content

    def test_create_spec_file_skips_if_exists(self, agents_repo, tmp_path):
        """Test create_spec_file doesn't overwrite existing spec."""
        agents_repo.agents_path = tmp_path / "agents"
        agents_repo.agents_path.mkdir()
        (agents_repo.agents_path / "specs" / "features").mkdir(parents=True)

        # Create existing spec
        spec_file = agents_repo.agents_path / "specs" / "features" / "issue-42.md"
        spec_file.write_text("# Existing spec")

        with patch.object(agents_repo, '_commit'):
            agents_repo.create_spec_file(
                issue_num=42,
                issue_title="Add dark mode",
                issue_body="Users want dark mode support",
                issue_url="https://github.com/user/repo/issues/42"
            )

        # Should not overwrite
        assert spec_file.read_text() == "# Existing spec"

    def test_create_task_file(self, agents_repo, tmp_path):
        """Test create_task_file creates task log."""
        agents_repo.agents_path = tmp_path / "agents"
        agents_repo.agents_path.mkdir()
        (agents_repo.agents_path / "tasks").mkdir()
        (agents_repo.agents_path / "templates").mkdir()

        # Create template file
        template = agents_repo.agents_path / "templates" / "task-log.md"
        template.write_text("""# Task: {title}

**Date:** {date}
**Agent:** {agent}
**Issue:** [#{issue_num}]({issue_url})

## Description

{description}""")

        with patch.object(agents_repo, '_commit'):
            task_path = agents_repo.create_task_file(
                agent_num=1,
                issue_num=42,
                issue_title="Add dark mode",
                issue_body="Users want dark mode support",
                issue_url="https://github.com/user/repo/issues/42"
            )

        # Check file was created with proper naming
        assert task_path.exists()
        assert task_path.parent.name == "agent-1"
        assert "add-dark-mode" in task_path.name

        content = task_path.read_text()
        assert "# Task: Add dark mode" in content
        assert "issue_number: 42" in content  # Frontmatter format
        assert "Users want dark mode support" in content

    def test_archive_task(self, agents_repo, tmp_path):
        """Test archive_task moves task to archive."""
        agents_repo.agents_path = tmp_path / "agents"
        agents_repo.agents_path.mkdir()

        # Create task directory and file
        task_dir = agents_repo.agents_path / "tasks" / "agent-1"
        task_dir.mkdir(parents=True)
        task_file = task_dir / "2025-01-15-test-task.md"
        task_file.write_text("# Test task")

        # Archive it
        agents_repo.archive_task(agent_num=1)

        # Check it was moved
        assert not task_file.exists()

        # Check archive exists (should be in YYYY-MM format)
        archive_dir = agents_repo.agents_path / "tasks" / "archive"
        assert archive_dir.exists()

        # Find the archived file
        archived_files = list(archive_dir.rglob("agent-1-*.md"))
        assert len(archived_files) == 1
        assert "test-task" in archived_files[0].name

    def test_archive_task_no_tasks(self, agents_repo, tmp_path):
        """Test archive_task when no tasks exist."""
        agents_repo.agents_path = tmp_path / "agents"
        agents_repo.agents_path.mkdir()
        (agents_repo.agents_path / "tasks").mkdir()

        # Should not raise error
        agents_repo.archive_task(agent_num=1)

    def test_slugify(self):
        """Test slugify helper function."""
        assert slugify("Add Dark Mode") == "add-dark-mode"
        assert slugify("Fix: Login Bug!") == "fix-login-bug"
        assert slugify("Update API v2.0") == "update-api-v20"
        assert slugify("Add   Multiple   Spaces") == "add-multiple-spaces"

    def test_add_to_gitignore_adds_agenttrees(self, agents_repo, tmp_path):
        """Test _add_to_gitignore adds .agenttrees/ to parent .gitignore."""
        agents_repo.project_path = tmp_path
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("__pycache__/\n*.pyc\n")

        agents_repo._add_to_gitignore()

        content = gitignore.read_text()
        assert ".agenttrees/" in content
        assert "__pycache__/" in content  # Original content preserved

    def test_add_to_gitignore_skips_if_exists(self, agents_repo, tmp_path):
        """Test _add_to_gitignore doesn't duplicate entry."""
        agents_repo.project_path = tmp_path
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".agenttrees/\n")

        original_content = gitignore.read_text()
        agents_repo._add_to_gitignore()

        # Should not modify (already has .agenttrees/)
        assert ".agenttrees/" in gitignore.read_text()
        assert gitignore.read_text().count(".agenttrees/") == 1

    @patch("agenttree.agents_repo.subprocess.run")
    def test_commit(self, mock_run, agents_repo):
        """Test _commit executes git commands."""
        agents_repo._commit("Test commit message")

        # Should run git add, commit, and push
        assert mock_run.call_count == 3

        calls = [c[0][0] for c in mock_run.call_args_list]

        # git add .
        assert "git" in calls[0]
        assert "add" in calls[0]

        # git commit -m "message"
        assert "git" in calls[1]
        assert "commit" in calls[1]

        # git push
        assert "git" in calls[2]
        assert "push" in calls[2]
