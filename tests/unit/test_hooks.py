"""Tests for agenttree.hooks module.

Tests the config-driven hook system for stage transitions.
"""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call

import pytest

from agenttree.issues import (
    Issue,
    Priority,
    IMPLEMENT,
    IMPLEMENTATION_REVIEW,
    RESEARCH,
    DEFINE,
    ACCEPTED,
    BACKLOG,
)


class TestValidationError:
    """Tests for ValidationError exception."""

    def test_validation_error_is_exception(self):
        """ValidationError should be an Exception."""
        from agenttree.hooks import ValidationError

        assert issubclass(ValidationError, Exception)

    def test_validation_error_message(self):
        """ValidationError should have a message."""
        from agenttree.hooks import ValidationError

        error = ValidationError("Test message")
        assert str(error) == "Test message"


class TestBuiltinValidators:
    """Tests for run_builtin_validator function."""

    def test_file_exists_success(self, tmp_path):
        """Should pass when file exists."""
        from agenttree.hooks import run_builtin_validator

        (tmp_path / "test.md").write_text("content")
        hook = {"type": "file_exists", "file": "test.md"}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_file_exists_failure(self, tmp_path):
        """Should return error when file doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        hook = {"type": "file_exists", "file": "missing.md"}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "missing.md" in errors[0]
        assert "does not exist" in errors[0]

    @patch('agenttree.hooks.has_commits_to_push')
    def test_has_commits_success(self, mock_has_commits, tmp_path):
        """Should pass when there are commits to push."""
        from agenttree.hooks import run_builtin_validator

        mock_has_commits.return_value = True
        hook = {"type": "has_commits"}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    @patch('agenttree.hooks.has_commits_to_push')
    def test_has_commits_failure(self, mock_has_commits, tmp_path):
        """Should return error when no commits to push."""
        from agenttree.hooks import run_builtin_validator

        mock_has_commits.return_value = False
        hook = {"type": "has_commits"}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "No commits" in errors[0]

    def test_field_check_success(self, tmp_path):
        """Should pass when field meets minimum threshold."""
        from agenttree.hooks import run_builtin_validator

        content = """# Review

```yaml
scores:
  correctness: 8
  average: 7.5
```
"""
        (tmp_path / "review.md").write_text(content)
        hook = {"type": "field_check", "file": "review.md", "path": "scores.average", "min": 7}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_field_check_below_minimum(self, tmp_path):
        """Should return error when field is below minimum."""
        from agenttree.hooks import run_builtin_validator

        content = """# Review

```yaml
scores:
  average: 5.0
```
"""
        (tmp_path / "review.md").write_text(content)
        hook = {"type": "field_check", "file": "review.md", "path": "scores.average", "min": 7}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "below minimum" in errors[0]

    def test_field_check_above_maximum(self, tmp_path):
        """Should return error when field is above maximum."""
        from agenttree.hooks import run_builtin_validator

        content = """# Review

```yaml
count: 15
```
"""
        (tmp_path / "review.md").write_text(content)
        hook = {"type": "field_check", "file": "review.md", "path": "count", "max": 10}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "above maximum" in errors[0]

    def test_field_check_missing_yaml(self, tmp_path):
        """Should return error when no YAML block found."""
        from agenttree.hooks import run_builtin_validator

        (tmp_path / "review.md").write_text("# Review\n\nNo YAML here")
        hook = {"type": "field_check", "file": "review.md", "path": "scores.average", "min": 7}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "No YAML block found" in errors[0]

    def test_section_check_not_empty_success(self, tmp_path):
        """Should pass when section has content."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Approach

This is the approach section with content.

## Next
"""
        (tmp_path / "spec.md").write_text(content)
        hook = {"type": "section_check", "file": "spec.md", "section": "Approach", "expect": "not_empty"}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_section_check_not_empty_failure(self, tmp_path):
        """Should return error when section is empty."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Approach

<!-- Just a comment -->

## Next
"""
        (tmp_path / "spec.md").write_text(content)
        hook = {"type": "section_check", "file": "spec.md", "section": "Approach", "expect": "not_empty"}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "is empty" in errors[0]

    def test_section_check_empty_success(self, tmp_path):
        """Should pass when section is empty (expected)."""
        from agenttree.hooks import run_builtin_validator

        content = """# Review

## Critical Issues

<!-- Must be empty before PR -->

## Suggestions

- Some suggestion
"""
        (tmp_path / "review.md").write_text(content)
        hook = {"type": "section_check", "file": "review.md", "section": "Critical Issues", "expect": "empty"}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_section_check_empty_failure(self, tmp_path):
        """Should return error when section has items but expected empty."""
        from agenttree.hooks import run_builtin_validator

        content = """# Review

## Critical Issues

- Security issue found

## Suggestions
"""
        (tmp_path / "review.md").write_text(content)
        hook = {"type": "section_check", "file": "review.md", "section": "Critical Issues", "expect": "empty"}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "is not empty" in errors[0]

    def test_section_check_all_checked_success(self, tmp_path):
        """Should pass when all checkboxes are checked."""
        from agenttree.hooks import run_builtin_validator

        content = """# Checklist

## Test Plan

- [x] Unit tests pass
- [x] Integration tests pass
- [x] Manual testing done

## Notes
"""
        (tmp_path / "checklist.md").write_text(content)
        hook = {"type": "section_check", "file": "checklist.md", "section": "Test Plan", "expect": "all_checked"}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_section_check_all_checked_failure(self, tmp_path):
        """Should return error when unchecked items exist."""
        from agenttree.hooks import run_builtin_validator

        content = """# Checklist

## Test Plan

- [x] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing done

## Notes
"""
        (tmp_path / "checklist.md").write_text(content)
        hook = {"type": "section_check", "file": "checklist.md", "section": "Test Plan", "expect": "all_checked"}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "Unchecked items" in errors[0]

    def test_pr_approved_success(self, tmp_path):
        """Should pass when PR is approved."""
        from agenttree.hooks import run_builtin_validator

        with patch('agenttree.hooks.get_pr_approval_status', return_value=True):
            hook = {"type": "pr_approved"}
            errors = run_builtin_validator(tmp_path, hook, pr_number=123)
            assert errors == []

    def test_pr_approved_failure(self, tmp_path):
        """Should return error when PR is not approved."""
        from agenttree.hooks import run_builtin_validator

        with patch('agenttree.hooks.get_pr_approval_status', return_value=False):
            hook = {"type": "pr_approved"}
            errors = run_builtin_validator(tmp_path, hook, pr_number=123)
            assert len(errors) == 1
            assert "not approved" in errors[0]

    def test_pr_approved_no_pr_number(self, tmp_path):
        """Should return error when no PR number available."""
        from agenttree.hooks import run_builtin_validator

        hook = {"type": "pr_approved"}
        errors = run_builtin_validator(tmp_path, hook, pr_number=None)
        assert len(errors) == 1
        assert "No PR number" in errors[0]

    def test_create_file_action(self, tmp_path):
        """Should create file from template."""
        from agenttree.hooks import run_builtin_validator

        # Create templates directory and template file
        templates_dir = tmp_path / "_agenttree" / "templates"
        templates_dir.mkdir(parents=True)
        (templates_dir / "review.md").write_text("# Review Template")

        with patch.object(Path, 'cwd', return_value=tmp_path):
            issue_dir = tmp_path / "issue"
            issue_dir.mkdir()
            hook = {"type": "create_file", "template": "review.md", "dest": "review.md"}

            errors = run_builtin_validator(issue_dir, hook)

        # Note: The create_file action uses absolute path from _agenttree/templates
        # This test verifies the hook runs without errors
        assert errors == []

    def test_unknown_hook_type_ignored(self, tmp_path):
        """Unknown hook types should be ignored silently."""
        from agenttree.hooks import run_builtin_validator

        hook = {"type": "future_validator"}
        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []


class TestCommandHooks:
    """Tests for run_command_hook function."""

    def test_command_success(self, tmp_path):
        """Should return empty errors on success."""
        from agenttree.hooks import run_command_hook

        hook = {"command": "echo hello"}
        errors = run_command_hook(tmp_path, hook)
        assert errors == []

    def test_command_failure(self, tmp_path):
        """Should return error message on failure."""
        from agenttree.hooks import run_command_hook

        hook = {"command": "exit 1"}
        errors = run_command_hook(tmp_path, hook)
        assert len(errors) == 1

    def test_command_timeout(self, tmp_path):
        """Should return error on timeout."""
        from agenttree.hooks import run_command_hook

        hook = {"command": "sleep 10", "timeout": 0.1}
        errors = run_command_hook(tmp_path, hook)
        assert len(errors) == 1
        assert "timed out" in errors[0]

    def test_command_variable_substitution(self, tmp_path):
        """Should substitute template variables in command."""
        from agenttree.hooks import run_command_hook

        # Create a file to verify the variable substitution worked
        hook = {"command": "echo {{issue_id}} > output.txt"}
        errors = run_command_hook(tmp_path, hook, issue_id="123")
        assert errors == []

        output = (tmp_path / "output.txt").read_text().strip()
        assert output == "123"


class TestExecuteHooks:
    """Tests for execute_hooks function."""

    def test_execute_hooks_collects_all_errors(self, tmp_path):
        """Should collect errors from all hooks."""
        from agenttree.hooks import execute_hooks
        from agenttree.config import SubstageConfig

        config = SubstageConfig(
            name="test",
            pre_completion=[
                {"type": "file_exists", "file": "missing1.md"},
                {"type": "file_exists", "file": "missing2.md"},
            ]
        )

        errors = execute_hooks(tmp_path, "test", config, "pre_completion")
        assert len(errors) == 2

    def test_execute_hooks_checks_output_file_on_pre_completion(self, tmp_path):
        """Should check output file exists when not optional."""
        from agenttree.hooks import execute_hooks
        from agenttree.config import SubstageConfig

        config = SubstageConfig(
            name="test",
            output="required.md",
            output_optional=False,
            pre_completion=[],
        )

        errors = execute_hooks(tmp_path, "test", config, "pre_completion")
        assert len(errors) == 1
        assert "required.md" in errors[0]

    def test_execute_hooks_skips_optional_output_check(self, tmp_path):
        """Should skip output check when output_optional is True."""
        from agenttree.hooks import execute_hooks
        from agenttree.config import SubstageConfig

        config = SubstageConfig(
            name="test",
            output="optional.md",
            output_optional=True,
            pre_completion=[],
        )

        errors = execute_hooks(tmp_path, "test", config, "pre_completion")
        assert errors == []


class TestExecuteExitHooks:
    """Tests for execute_exit_hooks function."""

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_raises_validation_error_on_failure(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """Should raise ValidationError when hooks fail."""
        from agenttree.hooks import execute_exit_hooks, ValidationError
        from agenttree.config import Config, StageConfig, SubstageConfig

        config = Config()
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = ["Error 1"]

        issue = Mock(spec=Issue)
        issue.id = "123"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None

        with pytest.raises(ValidationError, match="Error 1"):
            execute_exit_hooks(issue, "implement", "code")

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_multiple_errors_formatted(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """Should format multiple errors with numbered list."""
        from agenttree.hooks import execute_exit_hooks, ValidationError
        from agenttree.config import Config

        config = Config()
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = ["Error 1", "Error 2"]

        issue = Mock(spec=Issue)
        issue.id = "123"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None

        with pytest.raises(ValidationError) as exc_info:
            execute_exit_hooks(issue, "implement", "code")

        error_msg = str(exc_info.value)
        assert "Multiple validation errors" in error_msg
        assert "1." in error_msg
        assert "2." in error_msg


class TestExecuteEnterHooks:
    """Tests for execute_enter_hooks function."""

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_logs_warnings_but_does_not_raise(
        self, mock_get_dir, mock_load_config, mock_execute_hooks, capsys
    ):
        """Should log warnings but not raise on errors."""
        from agenttree.hooks import execute_enter_hooks
        from agenttree.config import Config

        config = Config()
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = ["Warning message"]

        issue = Mock(spec=Issue)
        issue.id = "123"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None

        # Should not raise
        execute_enter_hooks(issue, "implement", "code")


@pytest.fixture
def mock_issue():
    """Create a mock Issue object."""
    return Issue(
        id="023",
        slug="test-issue",
        title="Test Issue",
        created="2026-01-11T12:00:00Z",
        updated="2026-01-11T12:00:00Z",
        stage=IMPLEMENT,
        substage="code",
        branch="agenttree-agent-1-work",
    )


@pytest.fixture
def temp_git_repo(tmp_path):
    """Create a temporary git repository."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()

    # Initialize git repo
    subprocess.run(
        ["git", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )

    # Configure git
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )

    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo_path,
        check=True,
        capture_output=True
    )

    return repo_path


class TestGitUtilities:
    """Tests for git utility functions."""

    def test_get_current_branch(self, temp_git_repo, monkeypatch):
        """Should get the current git branch name."""
        from agenttree.hooks import get_current_branch

        monkeypatch.chdir(temp_git_repo)

        # Default branch should be main or master
        branch = get_current_branch()
        assert branch in ["main", "master"]

        # Create and checkout a new branch
        subprocess.run(
            ["git", "checkout", "-b", "test-branch"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )

        branch = get_current_branch()
        assert branch == "test-branch"

    def test_has_uncommitted_changes_no_changes(self, temp_git_repo, monkeypatch):
        """Should return False when there are no uncommitted changes."""
        from agenttree.hooks import has_uncommitted_changes

        monkeypatch.chdir(temp_git_repo)

        assert has_uncommitted_changes() is False

    def test_has_uncommitted_changes_with_unstaged_changes(self, temp_git_repo, monkeypatch):
        """Should return True with unstaged changes."""
        from agenttree.hooks import has_uncommitted_changes

        monkeypatch.chdir(temp_git_repo)

        # Modify a file
        (temp_git_repo / "README.md").write_text("Modified content")

        assert has_uncommitted_changes() is True

    def test_has_uncommitted_changes_with_staged_changes(self, temp_git_repo, monkeypatch):
        """Should return True with staged changes."""
        from agenttree.hooks import has_uncommitted_changes

        monkeypatch.chdir(temp_git_repo)

        # Create and stage a new file
        (temp_git_repo / "new_file.txt").write_text("New content")
        subprocess.run(
            ["git", "add", "new_file.txt"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )

        assert has_uncommitted_changes() is True

    @patch('subprocess.run')
    def test_get_default_branch_from_symbolic_ref(self, mock_run):
        """Should detect default branch from origin/HEAD."""
        from agenttree.hooks import get_default_branch

        mock_run.return_value = MagicMock(
            stdout="refs/remotes/origin/main\n",
            returncode=0
        )

        result = get_default_branch()
        assert result == "main"

    @patch('subprocess.run')
    def test_get_default_branch_fallback_to_main(self, mock_run):
        """Should fall back to 'main' when origin/HEAD doesn't exist."""
        from agenttree.hooks import get_default_branch

        # First call fails (no symbolic-ref), second succeeds (main exists)
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=128),  # symbolic-ref fails
            MagicMock(stdout="abc123\n", returncode=0),  # origin/main exists
        ]

        result = get_default_branch()
        assert result == "main"

    @patch('subprocess.run')
    def test_get_default_branch_fallback_to_master(self, mock_run):
        """Should fall back to 'master' when neither origin/HEAD nor origin/main exist."""
        from agenttree.hooks import get_default_branch

        # Both calls fail
        mock_run.side_effect = [
            MagicMock(stdout="", returncode=128),  # symbolic-ref fails
            MagicMock(stdout="", returncode=128),  # origin/main doesn't exist
        ]

        result = get_default_branch()
        assert result == "master"

    def test_has_commits_to_push_no_commits(self, temp_git_repo, monkeypatch):
        """Should return False when there are no unpushed commits."""
        from agenttree.hooks import has_commits_to_push

        monkeypatch.chdir(temp_git_repo)

        # Create a bare repo to act as remote
        remote_path = temp_git_repo.parent / "remote.git"
        subprocess.run(
            ["git", "init", "--bare", str(remote_path)],
            check=True,
            capture_output=True
        )

        # Add remote and push
        subprocess.run(
            ["git", "remote", "add", "origin", str(remote_path)],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )

        assert has_commits_to_push() is False

    def test_has_commits_to_push_with_commits(self, temp_git_repo, monkeypatch):
        """Should return True when there are unpushed commits."""
        from agenttree.hooks import has_commits_to_push

        monkeypatch.chdir(temp_git_repo)

        # Create a bare repo to act as remote
        remote_path = temp_git_repo.parent / "remote.git"
        subprocess.run(
            ["git", "init", "--bare", str(remote_path)],
            check=True,
            capture_output=True
        )

        # Add remote and push
        subprocess.run(
            ["git", "remote", "add", "origin", str(remote_path)],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "HEAD"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )

        # Create a new commit
        (temp_git_repo / "new_file.txt").write_text("New content")
        subprocess.run(
            ["git", "add", "new_file.txt"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Add new file"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )

        assert has_commits_to_push() is True

    @patch('subprocess.run')
    def test_push_branch_to_remote(self, mock_run):
        """Should push branch to remote with -u flag."""
        from agenttree.hooks import push_branch_to_remote

        mock_run.return_value = MagicMock(returncode=0)

        push_branch_to_remote("test-branch")

        mock_run.assert_called_once_with(
            ["git", "push", "-u", "origin", "test-branch:test-branch"],
            check=True,
            capture_output=True,
            text=True
        )

    @patch('subprocess.run')
    def test_get_repo_remote_name_ssh_url(self, mock_run):
        """Should parse owner/repo from SSH URL."""
        from agenttree.hooks import get_repo_remote_name

        mock_run.return_value = MagicMock(
            stdout="git@github.com:owner/repo.git\n",
            returncode=0
        )

        result = get_repo_remote_name()

        assert result == "owner/repo"
        mock_run.assert_called_once()

    @patch('subprocess.run')
    def test_get_repo_remote_name_https_url(self, mock_run):
        """Should parse owner/repo from HTTPS URL."""
        from agenttree.hooks import get_repo_remote_name

        mock_run.return_value = MagicMock(
            stdout="https://github.com/owner/repo.git\n",
            returncode=0
        )

        result = get_repo_remote_name()

        assert result == "owner/repo"

    @patch('subprocess.run')
    def test_get_repo_remote_name_https_no_git_suffix(self, mock_run):
        """Should parse owner/repo from HTTPS URL without .git."""
        from agenttree.hooks import get_repo_remote_name

        mock_run.return_value = MagicMock(
            stdout="https://github.com/owner/repo\n",
            returncode=0
        )

        result = get_repo_remote_name()

        assert result == "owner/repo"

    def test_generate_pr_body(self, mock_issue):
        """Should generate PR body with issue information."""
        from agenttree.hooks import generate_pr_body

        body = generate_pr_body(mock_issue)

        assert "Issue #023" in body
        assert "Test Issue" in body
        assert "agenttree" in body.lower()  # Should mention agenttree
        assert "Review Checklist" in body

    @patch('subprocess.run')
    def test_auto_commit_changes_no_changes(self, mock_run):
        """Should return False when there are no changes to commit."""
        from agenttree.hooks import auto_commit_changes

        # Mock git status to show no changes
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=0
        )

        result = auto_commit_changes(Mock(), IMPLEMENT)

        assert result is False
        # Should only call git status, not git add or commit
        assert mock_run.call_count == 1

    @patch('agenttree.hooks.has_uncommitted_changes')
    @patch('subprocess.run')
    def test_auto_commit_changes_with_changes(self, mock_run, mock_has_changes):
        """Should commit changes when they exist."""
        from agenttree.hooks import auto_commit_changes

        mock_has_changes.return_value = True
        mock_run.return_value = MagicMock(returncode=0)

        issue = Issue(
            id="023",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=IMPLEMENT,
        )

        result = auto_commit_changes(issue, IMPLEMENT)

        assert result is True
        # Should call git add -A and git commit
        assert mock_run.call_count == 2
        calls = mock_run.call_args_list
        assert calls[0][0][0] == ["git", "add", "-A"]
        assert calls[1][0][0][0] == "git"
        assert calls[1][0][0][1] == "commit"
        assert calls[1][0][0][2] == "-m"

    def test_generate_commit_message(self, mock_issue):
        """Should generate appropriate commit message."""
        from agenttree.hooks import generate_commit_message

        msg = generate_commit_message(mock_issue, IMPLEMENT)

        assert "Implement" in msg
        assert "#023" in msg
        assert "Test Issue" in msg


class TestCheckAndStartBlockedIssues:
    """Tests for check_and_start_blocked_issues hook."""

    @pytest.fixture
    def accepted_issue(self):
        """Create an issue that just reached ACCEPTED stage."""
        return Issue(
            id="001",
            slug="completed-issue",
            title="Completed Issue",
            created="2026-01-15T12:00:00Z",
            updated="2026-01-15T12:00:00Z",
            stage=ACCEPTED,
        )

    @pytest.fixture
    def blocked_issue(self):
        """Create an issue blocked in backlog with dependencies."""
        return Issue(
            id="002",
            slug="blocked-issue",
            title="Blocked Issue",
            created="2026-01-15T12:00:00Z",
            updated="2026-01-15T12:00:00Z",
            stage=BACKLOG,
            dependencies=["001"],
        )

    @patch('agenttree.hooks.is_running_in_container', return_value=True)
    def test_check_and_start_blocked_issues_in_container(self, mock_in_container, accepted_issue):
        """Should exit early when running in container."""
        from agenttree.hooks import check_and_start_blocked_issues

        # Mock at the source module since import happens inside the function
        with patch('agenttree.issues.get_blocked_issues') as mock_get_blocked:
            with patch('subprocess.run') as mock_run:
                check_and_start_blocked_issues(accepted_issue)

                # Should not call get_blocked_issues when in container (returns early)
                mock_get_blocked.assert_not_called()
                mock_run.assert_not_called()

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_check_and_start_blocked_issues_no_blocked(self, mock_in_container, accepted_issue):
        """Should do nothing when no blocked issues exist."""
        from agenttree.hooks import check_and_start_blocked_issues

        with patch('agenttree.issues.get_blocked_issues', return_value=[]) as mock_get_blocked:
            with patch('subprocess.run') as mock_run:
                check_and_start_blocked_issues(accepted_issue)

                # Should call get_blocked_issues
                mock_get_blocked.assert_called_once_with(accepted_issue.id)

                # Should not call subprocess.run (no agents to start)
                mock_run.assert_not_called()

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_check_and_start_blocked_issues_starts_ready(
        self, mock_in_container, accepted_issue, blocked_issue
    ):
        """Should start agents when all dependencies are met."""
        from agenttree.hooks import check_and_start_blocked_issues

        with patch('agenttree.issues.get_blocked_issues', return_value=[blocked_issue]):
            with patch('agenttree.issues.check_dependencies_met', return_value=(True, [])):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stderr="")

                    check_and_start_blocked_issues(accepted_issue)

                    # Should call agenttree start for the blocked issue
                    mock_run.assert_called_once_with(
                        ["agenttree", "start", blocked_issue.id],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_check_and_start_blocked_issues_skips_unmet(
        self, mock_in_container, accepted_issue, blocked_issue
    ):
        """Should skip issues with unmet dependencies."""
        from agenttree.hooks import check_and_start_blocked_issues

        with patch('agenttree.issues.get_blocked_issues', return_value=[blocked_issue]):
            # Dependencies not met - issue 003 is still pending
            with patch('agenttree.issues.check_dependencies_met', return_value=(False, ["003"])):
                with patch('subprocess.run') as mock_run:
                    check_and_start_blocked_issues(accepted_issue)

                    # Should not call subprocess.run (deps not met)
                    mock_run.assert_not_called()

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_check_and_start_blocked_issues_subprocess_failure(
        self, mock_in_container, accepted_issue, blocked_issue
    ):
        """Should handle subprocess failures gracefully."""
        from agenttree.hooks import check_and_start_blocked_issues

        with patch('agenttree.issues.get_blocked_issues', return_value=[blocked_issue]):
            with patch('agenttree.issues.check_dependencies_met', return_value=(True, [])):
                with patch('subprocess.run') as mock_run:
                    # Simulate subprocess failure
                    mock_run.return_value = MagicMock(returncode=1, stderr="Error starting agent")

                    # Should not raise - errors are caught and logged
                    check_and_start_blocked_issues(accepted_issue)

                    # Should have attempted to start
                    mock_run.assert_called_once()

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_check_and_start_blocked_issues_exception_handling(
        self, mock_in_container, accepted_issue, blocked_issue
    ):
        """Should handle exceptions gracefully without crashing."""
        from agenttree.hooks import check_and_start_blocked_issues

        with patch('agenttree.issues.get_blocked_issues', return_value=[blocked_issue]):
            with patch('agenttree.issues.check_dependencies_met', return_value=(True, [])):
                with patch('subprocess.run') as mock_run:
                    # Simulate an exception (e.g., timeout)
                    mock_run.side_effect = Exception("Timeout exceeded")

                    # Should not raise - exceptions are caught and logged
                    check_and_start_blocked_issues(accepted_issue)

                    # Should have attempted to start
                    mock_run.assert_called_once()

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_check_and_start_blocked_issues_multiple_blocked(
        self, mock_in_container, accepted_issue
    ):
        """Should process multiple blocked issues correctly."""
        from agenttree.hooks import check_and_start_blocked_issues

        blocked1 = Issue(
            id="002",
            slug="blocked-1",
            title="Blocked 1",
            created="2026-01-15T12:00:00Z",
            updated="2026-01-15T12:00:00Z",
            stage=BACKLOG,
            dependencies=["001"],
        )
        blocked2 = Issue(
            id="003",
            slug="blocked-2",
            title="Blocked 2",
            created="2026-01-15T12:00:00Z",
            updated="2026-01-15T12:00:00Z",
            stage=BACKLOG,
            dependencies=["001"],
        )

        with patch('agenttree.issues.get_blocked_issues', return_value=[blocked1, blocked2]):
            # blocked1 has all deps met, blocked2 does not
            def check_deps(issue):
                if issue.id == "002":
                    return (True, [])
                return (False, ["004"])

            with patch('agenttree.issues.check_dependencies_met', side_effect=check_deps):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(returncode=0, stderr="")

                    check_and_start_blocked_issues(accepted_issue)

                    # Should only start blocked1 (blocked2 has unmet deps)
                    mock_run.assert_called_once_with(
                        ["agenttree", "start", "002"],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )


class TestCleanupIssueAgent:
    """Tests for cleanup_issue_agent function."""

    def test_no_agent_to_cleanup(self):
        """Should return early if no agent exists for issue."""
        from agenttree.hooks import cleanup_issue_agent

        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=ACCEPTED,
        )

        with patch('agenttree.state.get_active_agent', return_value=None) as mock_get:
            cleanup_issue_agent(issue)
            mock_get.assert_called_once_with("001")

    def test_cleanup_stops_tmux_session(self):
        """Should stop tmux session if it exists."""
        from agenttree.hooks import cleanup_issue_agent

        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=ACCEPTED,
        )

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agenttree-001"
        mock_agent.container = "agenttree-agent-1"

        with patch('agenttree.state.get_active_agent', return_value=mock_agent):
            with patch('agenttree.state.unregister_agent'):
                with patch('agenttree.tmux.session_exists', return_value=True) as mock_exists:
                    with patch('agenttree.tmux.kill_session') as mock_kill:
                        with patch('agenttree.container.get_container_runtime') as mock_runtime:
                            mock_runtime.return_value.runtime = None  # No container runtime
                            cleanup_issue_agent(issue)
                            mock_exists.assert_called_once_with("agenttree-001")
                            mock_kill.assert_called_once_with("agenttree-001")

    def test_cleanup_stops_container_with_runtime(self):
        """Should use detected container runtime to stop container."""
        from agenttree.hooks import cleanup_issue_agent

        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=ACCEPTED,
        )

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agenttree-001"
        mock_agent.container = "agenttree-agent-1"

        with patch('agenttree.state.get_active_agent', return_value=mock_agent):
            with patch('agenttree.state.unregister_agent'):
                with patch('agenttree.tmux.session_exists', return_value=False):
                    with patch('agenttree.container.get_container_runtime') as mock_runtime:
                        mock_runtime.return_value.runtime = "docker"
                        with patch('subprocess.run') as mock_run:
                            mock_run.return_value = MagicMock(returncode=0)
                            cleanup_issue_agent(issue)
                            # Should call docker stop and docker rm
                            calls = mock_run.call_args_list
                            assert any("stop" in str(c) and "docker" in str(c) for c in calls)
                            assert any("rm" in str(c) and "docker" in str(c) for c in calls)

    def test_cleanup_unregisters_agent(self):
        """Should unregister agent to free port."""
        from agenttree.hooks import cleanup_issue_agent

        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=ACCEPTED,
        )

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agenttree-001"
        mock_agent.container = "agenttree-agent-1"

        with patch('agenttree.state.get_active_agent', return_value=mock_agent):
            with patch('agenttree.state.unregister_agent') as mock_unregister:
                with patch('agenttree.tmux.session_exists', return_value=False):
                    with patch('agenttree.container.get_container_runtime') as mock_runtime:
                        mock_runtime.return_value.runtime = None
                        cleanup_issue_agent(issue)
                        mock_unregister.assert_called_once_with("001")

    def test_cleanup_handles_tmux_failure_gracefully(self):
        """Should continue cleanup even if tmux operations fail."""
        from agenttree.hooks import cleanup_issue_agent

        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=ACCEPTED,
        )

        mock_agent = MagicMock()
        mock_agent.tmux_session = "agenttree-001"
        mock_agent.container = "agenttree-agent-1"

        with patch('agenttree.state.get_active_agent', return_value=mock_agent):
            with patch('agenttree.state.unregister_agent') as mock_unregister:
                with patch('agenttree.tmux.session_exists', side_effect=Exception("tmux error")):
                    with patch('agenttree.container.get_container_runtime') as mock_runtime:
                        mock_runtime.return_value.runtime = None
                        # Should not raise, should continue to unregister
                        cleanup_issue_agent(issue)
                        mock_unregister.assert_called_once_with("001")


class TestBackwardCompatibility:
    """Tests for backward compatibility aliases."""

    def test_execute_pre_hooks_alias(self):
        """execute_pre_hooks should be aliased to execute_exit_hooks."""
        from agenttree.hooks import execute_pre_hooks, execute_exit_hooks

        assert execute_pre_hooks is execute_exit_hooks

    def test_execute_post_hooks_alias(self):
        """execute_post_hooks should be aliased to execute_enter_hooks."""
        from agenttree.hooks import execute_post_hooks, execute_enter_hooks

        assert execute_post_hooks is execute_enter_hooks


class TestHostOnlyOption:
    """Tests for host_only option in shell command hooks."""

    @patch('agenttree.hooks.is_running_in_container', return_value=True)
    def test_host_only_skips_in_container(self, mock_in_container, tmp_path):
        """Shell commands with host_only=True should be skipped in container."""
        from agenttree.hooks import run_command_hook

        hook = {"command": "echo 'should not run'", "host_only": True}
        errors = run_command_hook(tmp_path, hook)

        # Should return empty (skipped), not error
        assert errors == []

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_host_only_runs_on_host(self, mock_in_container, tmp_path):
        """Shell commands with host_only=True should run on host."""
        from agenttree.hooks import run_command_hook

        hook = {"command": "echo 'running on host'", "host_only": True}
        errors = run_command_hook(tmp_path, hook)

        assert errors == []

    @patch('agenttree.hooks.is_running_in_container', return_value=True)
    def test_non_host_only_runs_in_container(self, mock_in_container, tmp_path):
        """Shell commands without host_only should run in container."""
        from agenttree.hooks import run_command_hook

        hook = {"command": "echo 'running'"}
        errors = run_command_hook(tmp_path, hook)

        assert errors == []


class TestMergeStrategyUsage:
    """Tests for configurable merge strategy."""

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    @patch('agenttree.github.merge_pr')
    @patch('agenttree.config.load_config')
    def test_merge_uses_config_strategy(self, mock_load_config, mock_merge_pr, mock_container):
        """_action_merge_pr should use config.merge_strategy."""
        from agenttree.hooks import _action_merge_pr
        from agenttree.config import Config

        # Set up config with rebase strategy
        mock_config = Config(merge_strategy="rebase")
        mock_load_config.return_value = mock_config

        _action_merge_pr(pr_number=123)

        mock_merge_pr.assert_called_once_with(123, method="rebase")

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    @patch('agenttree.github.merge_pr')
    @patch('agenttree.config.load_config')
    def test_merge_default_squash(self, mock_load_config, mock_merge_pr, mock_container):
        """Default merge strategy should be squash."""
        from agenttree.hooks import _action_merge_pr
        from agenttree.config import Config

        mock_config = Config()  # Uses default squash
        mock_load_config.return_value = mock_config

        _action_merge_pr(pr_number=456)

        mock_merge_pr.assert_called_once_with(456, method="squash")


class TestHostActionHooks:
    """Tests for host action hooks (post_pr_create, post_merge, post_accepted)."""

    @patch('agenttree.hooks.run_host_hooks')
    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    @patch('agenttree.hooks.push_branch_to_remote')
    @patch('agenttree.github.create_pr')
    @patch('agenttree.issues.update_issue_metadata')
    @patch('agenttree.hooks.get_current_branch', return_value='test-branch')
    @patch('agenttree.hooks.has_uncommitted_changes', return_value=False)
    @patch('agenttree.config.load_config')
    def test_post_pr_create_hooks_called(
        self, mock_load_config, mock_uncommitted, mock_branch,
        mock_update, mock_create_pr, mock_push, mock_container, mock_run_hooks
    ):
        """post_pr_create hooks should be called after PR creation."""
        from agenttree.hooks import _action_create_pr
        from agenttree.config import Config, HooksConfig

        mock_pr = MagicMock()
        mock_pr.number = 123
        mock_pr.url = "https://github.com/owner/repo/pull/123"
        mock_create_pr.return_value = mock_pr

        hooks_config = HooksConfig(
            post_pr_create=[{"command": "echo 'PR created'", "host_only": True}]
        )
        mock_config = Config(hooks=hooks_config)
        mock_load_config.return_value = mock_config

        _action_create_pr(Path("/tmp"), issue_id="001", issue_title="Test")

        # Verify run_host_hooks was called with post_pr_create hooks
        mock_run_hooks.assert_called_once()
        call_args = mock_run_hooks.call_args
        assert call_args[0][0] == hooks_config.post_pr_create

    @patch('agenttree.hooks.run_host_hooks')
    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    @patch('agenttree.github.merge_pr')
    @patch('agenttree.config.load_config')
    def test_post_merge_hooks_called(
        self, mock_load_config, mock_merge_pr, mock_container, mock_run_hooks
    ):
        """post_merge hooks should be called after merge."""
        from agenttree.hooks import _action_merge_pr
        from agenttree.config import Config, HooksConfig

        hooks_config = HooksConfig(
            post_merge=[{"command": "echo 'merged'"}]
        )
        mock_config = Config(hooks=hooks_config)
        mock_load_config.return_value = mock_config

        _action_merge_pr(pr_number=123)

        # Verify run_host_hooks was called with post_merge hooks
        mock_run_hooks.assert_called_once()
        call_args = mock_run_hooks.call_args
        assert call_args[0][0] == hooks_config.post_merge

    @patch('agenttree.hooks.run_host_hooks')
    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    @patch('agenttree.issues.get_blocked_issues', return_value=[])
    @patch('agenttree.config.load_config')
    def test_post_accepted_hooks_called(
        self, mock_load_config, mock_blocked, mock_container, mock_run_hooks
    ):
        """post_accepted hooks should be called when issue is accepted."""
        from agenttree.hooks import check_and_start_blocked_issues
        from agenttree.config import Config, HooksConfig

        hooks_config = HooksConfig(
            post_accepted=[{"command": "echo 'completed'"}]
        )
        mock_config = Config(hooks=hooks_config)
        mock_load_config.return_value = mock_config

        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=ACCEPTED,
        )

        check_and_start_blocked_issues(issue)

        # Verify run_host_hooks was called with post_accepted hooks
        mock_run_hooks.assert_called_once()
        call_args = mock_run_hooks.call_args
        assert call_args[0][0] == hooks_config.post_accepted


class TestRunHostHooks:
    """Tests for run_host_hooks function."""

    def test_run_host_hooks_executes_commands(self, tmp_path):
        """run_host_hooks should execute command hooks."""
        from agenttree.hooks import run_host_hooks

        # Create a marker file to verify execution
        hooks = [{"command": f"touch {tmp_path}/marker.txt"}]
        run_host_hooks(hooks, {"issue_id": "001"})

        assert (tmp_path / "marker.txt").exists()

    @patch('agenttree.hooks.is_running_in_container', return_value=True)
    def test_run_host_hooks_respects_host_only(self, mock_container, tmp_path):
        """run_host_hooks should skip host_only commands in container."""
        from agenttree.hooks import run_host_hooks

        hooks = [{"command": f"touch {tmp_path}/marker.txt", "host_only": True}]
        run_host_hooks(hooks, {"issue_id": "001"})

        # File should NOT be created because we're "in container"
        assert not (tmp_path / "marker.txt").exists()

    def test_run_host_hooks_substitutes_variables(self, tmp_path):
        """run_host_hooks should substitute template variables."""
        from agenttree.hooks import run_host_hooks

        hooks = [{"command": f"echo '{{{{issue_id}}}}' > {tmp_path}/output.txt"}]
        run_host_hooks(hooks, {"issue_id": "042"})

        content = (tmp_path / "output.txt").read_text().strip()
        assert content == "042"

    def test_run_host_hooks_handles_errors_gracefully(self, tmp_path, capsys):
        """run_host_hooks should log errors but not raise."""
        from agenttree.hooks import run_host_hooks

        hooks = [{"command": "exit 1"}]  # Command that fails

        # Should not raise
        run_host_hooks(hooks, {"issue_id": "001"})


class TestCursorReviewRemoved:
    """Tests verifying hardcoded Cursor review is removed."""

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    @patch('agenttree.hooks.push_branch_to_remote')
    @patch('agenttree.github.create_pr')
    @patch('agenttree.issues.update_issue_metadata')
    @patch('agenttree.hooks.get_current_branch', return_value='test-branch')
    @patch('agenttree.hooks.has_uncommitted_changes', return_value=False)
    @patch('agenttree.config.load_config')
    @patch('subprocess.run')
    def test_no_hardcoded_cursor_comment(
        self, mock_subprocess, mock_load_config, mock_uncommitted, mock_branch,
        mock_update, mock_create_pr, mock_push, mock_container
    ):
        """_action_create_pr should NOT make hardcoded cursor review comment."""
        from agenttree.hooks import _action_create_pr
        from agenttree.config import Config, HooksConfig

        mock_pr = MagicMock()
        mock_pr.number = 123
        mock_pr.url = "https://github.com/owner/repo/pull/123"
        mock_create_pr.return_value = mock_pr

        # No hooks configured
        mock_config = Config(hooks=HooksConfig())
        mock_load_config.return_value = mock_config

        _action_create_pr(Path("/tmp"), issue_id="001", issue_title="Test")

        # Verify subprocess.run was NOT called with cursor comment
        for call in mock_subprocess.call_args_list:
            args = call[0][0] if call[0] else call[1].get('args', [])
            if isinstance(args, list) and "gh" in args and "comment" in args:
                assert "@cursor" not in str(args), "Hardcoded cursor comment found!"


class TestPreCompletionPostStartHooks:
    """Tests for renamed hook fields (pre_completion/post_start)."""

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_execute_exit_hooks_uses_pre_completion(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """execute_exit_hooks should use pre_completion field."""
        from agenttree.hooks import execute_exit_hooks
        from agenttree.config import Config

        config = Config()
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = []

        issue = Mock(spec=Issue)
        issue.id = "123"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None

        execute_exit_hooks(issue, "implement", "code")

        # Verify execute_hooks was called with "pre_completion" event
        mock_execute_hooks.assert_called_once()
        call_args = mock_execute_hooks.call_args
        assert call_args[0][3] == "pre_completion"

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_execute_enter_hooks_uses_post_start(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """execute_enter_hooks should use post_start field."""
        from agenttree.hooks import execute_enter_hooks
        from agenttree.config import Config

        config = Config()
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = []

        issue = Mock(spec=Issue)
        issue.id = "123"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None
        issue.stage = IMPLEMENT

        execute_enter_hooks(issue, "implement", "code")

        # Verify execute_hooks was called with "post_start" event
        mock_execute_hooks.assert_called_once()
        call_args = mock_execute_hooks.call_args
        assert call_args[0][3] == "post_start"
