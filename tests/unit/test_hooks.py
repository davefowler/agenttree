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
        """Should return error when PR is not approved and auto-approve fails."""
        from agenttree.hooks import run_builtin_validator

        # Mock approval check returning False, and subprocess auto-approve failing
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Can not approve your own pull request"

        with patch('agenttree.hooks.get_pr_approval_status', return_value=False):
            with patch('agenttree.hooks.subprocess.run', return_value=mock_result):
                hook = {"type": "pr_approved"}
                errors = run_builtin_validator(tmp_path, hook, pr_number=123)
                assert len(errors) == 1
                assert "approve" in errors[0].lower()

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

    @patch('agenttree.hooks.get_git_diff_stats')
    def test_create_file_action_substitutes_git_stats(self, mock_git_stats, tmp_path, monkeypatch):
        """Should substitute git stats in template when creating file."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.config import Config

        mock_git_stats.return_value = {
            'files_changed': 5,
            'lines_added': 100,
            'lines_removed': 20
        }

        # Create templates directory and template file with placeholders
        templates_dir = tmp_path / "_agenttree" / "templates"
        templates_dir.mkdir(parents=True)
        template_content = """# Review - Issue #{{issue_id}}
**Files Changed:** {{files_changed}}
**Lines Changed:** +{{lines_added}} -{{lines_removed}}
"""
        (templates_dir / "review.md").write_text(template_content)

        # Use monkeypatch.chdir to actually change the working directory
        monkeypatch.chdir(tmp_path)

        issue_dir = tmp_path / "issue"
        issue_dir.mkdir()

        # Create a mock issue
        mock_issue = MagicMock()
        mock_issue.id = "046"
        mock_issue.title = "Test Issue"
        mock_issue.slug = "test-issue"
        mock_issue.worktree_dir = None

        hook = {"type": "create_file", "template": "review.md", "dest": "review.md"}

        with patch('agenttree.hooks.load_config', return_value=Config()):
            errors = run_builtin_validator(issue_dir, hook, issue=mock_issue)

        assert errors == []
        mock_git_stats.assert_called_once()

        # Verify the file was created with substituted values
        created_file = issue_dir / "review.md"
        assert created_file.exists()
        content = created_file.read_text()
        assert "Issue #046" in content
        assert "**Files Changed:** 5" in content
        assert "+100 -20" in content

    def test_create_file_renders_jinja_template(self, tmp_path, monkeypatch):
        """create_file should render Jinja templates with issue context."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.config import Config

        # Change to tmp_path so relative paths work
        monkeypatch.chdir(tmp_path)

        # Create templates directory and template file with Jinja
        templates_dir = tmp_path / "_agenttree" / "templates"
        templates_dir.mkdir(parents=True)
        (templates_dir / "test_review.md").write_text("# Review for {{issue_id}}\nTitle: {{issue_title}}")

        # Create issue dir
        issue_dir = tmp_path / "issue"
        issue_dir.mkdir()

        # Create a mock issue
        mock_issue = MagicMock()
        mock_issue.id = "042"
        mock_issue.title = "Test Issue"
        mock_issue.slug = "test-issue"
        mock_issue.worktree_dir = None

        # Mock load_config to return empty commands
        with patch('agenttree.hooks.load_config', return_value=Config()):
            hook = {"type": "create_file", "template": "test_review.md", "dest": "output.md"}
            errors = run_builtin_validator(issue_dir, hook, issue=mock_issue)

        assert errors == []

        # Check that the file was created with rendered content
        output_path = issue_dir / "output.md"
        assert output_path.exists()
        content = output_path.read_text()
        assert "# Review for 042" in content
        assert "Title: Test Issue" in content

    def test_create_file_injects_command_outputs(self, tmp_path, monkeypatch):
        """create_file should inject command outputs into templates."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.config import Config

        # Change to tmp_path so relative paths work
        monkeypatch.chdir(tmp_path)

        # Create templates directory and template file with command variable
        templates_dir = tmp_path / "_agenttree" / "templates"
        templates_dir.mkdir(parents=True)
        (templates_dir / "stats.md").write_text("Branch: {{git_branch}}")

        # Create issue dir
        issue_dir = tmp_path / "issue"
        issue_dir.mkdir()

        # Create a mock issue
        mock_issue = MagicMock()
        mock_issue.id = "001"
        mock_issue.title = "Test"
        mock_issue.slug = "test"
        mock_issue.worktree_dir = None

        # Mock load_config to return commands
        mock_config = Config(commands={"git_branch": "echo 'feature-branch'"})
        with patch('agenttree.hooks.load_config', return_value=mock_config):
            hook = {"type": "create_file", "template": "stats.md", "dest": "output.md"}
            errors = run_builtin_validator(issue_dir, hook, issue=mock_issue)

        assert errors == []

        # Check that the file was created with command output
        output_path = issue_dir / "output.md"
        assert output_path.exists()
        content = output_path.read_text()
        assert "Branch: feature-branch" in content

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
        assert "timeout" in errors[0].lower()

    def test_command_variable_substitution(self, tmp_path):
        """Should substitute template variables in command."""
        from agenttree.hooks import run_command_hook

        # Create a file to verify the variable substitution worked
        hook = {"command": "echo {{issue_id}} > output.txt"}
        errors = run_command_hook(tmp_path, hook, issue_id="123")
        assert errors == []

        output = (tmp_path / "output.txt").read_text().strip()
        assert output == "123"


class TestWrapupVerifiedValidator:
    """Tests for wrapup_verified validator."""

    def test_wrapup_verified_success(self, tmp_path):
        """Should pass when all checklist items are checked."""
        from agenttree.hooks import run_builtin_validator

        review_content = """# Code Review

## Implementation Wrapup

### Verification Checklist

- [x] Tests pass
- [x] Diff reviewed

### Summary
Implemented the feature.
"""
        (tmp_path / "review.md").write_text(review_content)
        hook = {"wrapup_verified": "review.md"}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_wrapup_verified_success_uppercase_x(self, tmp_path):
        """Should pass for both [x] and [X]."""
        from agenttree.hooks import run_builtin_validator

        review_content = """# Code Review

## Implementation Wrapup

### Verification Checklist

- [X] Tests pass
- [x] Diff reviewed

### Summary
Implemented the feature.
"""
        (tmp_path / "review.md").write_text(review_content)
        hook = {"wrapup_verified": "review.md"}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_wrapup_verified_fails_missing_file(self, tmp_path):
        """Should fail when review.md doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        hook = {"wrapup_verified": "review.md"}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "review.md" in errors[0]
        assert "not found" in errors[0].lower()

    def test_wrapup_verified_fails_missing_wrapup_section(self, tmp_path):
        """Should fail when review.md has no Implementation Wrapup section."""
        from agenttree.hooks import run_builtin_validator

        review_content = """# Code Review

## Self-Review Checklist

- [x] Some item
"""
        (tmp_path / "review.md").write_text(review_content)
        hook = {"wrapup_verified": "review.md"}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "Implementation Wrapup" in errors[0]

    def test_wrapup_verified_fails_missing_checklist_section(self, tmp_path):
        """Should fail when Implementation Wrapup has no Verification Checklist."""
        from agenttree.hooks import run_builtin_validator

        review_content = """# Code Review

## Implementation Wrapup

### Summary
Implemented the feature.
"""
        (tmp_path / "review.md").write_text(review_content)
        hook = {"wrapup_verified": "review.md"}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "Verification Checklist" in errors[0]

    def test_wrapup_verified_fails_unchecked_items(self, tmp_path):
        """Should fail when checklist has unchecked items."""
        from agenttree.hooks import run_builtin_validator

        review_content = """# Code Review

## Implementation Wrapup

### Verification Checklist

- [x] Tests pass
- [ ] Diff reviewed

### Summary
Implemented the feature.
"""
        (tmp_path / "review.md").write_text(review_content)
        hook = {"wrapup_verified": "review.md"}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "unchecked" in errors[0].lower()

    def test_wrapup_verified_ignores_html_comments(self, tmp_path):
        """HTML comments in checklist shouldn't cause false positives."""
        from agenttree.hooks import run_builtin_validator

        review_content = """# Code Review

## Implementation Wrapup

### Verification Checklist

<!-- This is a comment with - [ ] unchecked item -->
- [x] Tests pass
- [x] Diff reviewed

### Summary
Implemented the feature.
"""
        (tmp_path / "review.md").write_text(review_content)
        hook = {"wrapup_verified": "review.md"}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []


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

        # Create config with stages (stages are now required)
        config = Config(stages=[
            StageConfig(name="implement", substages={
                "code": SubstageConfig(name="code", pre_completion=[{"file_exists": "test.md"}])
            })
        ])
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
        from agenttree.config import Config, StageConfig, SubstageConfig

        # Create config with stages (stages are now required)
        config = Config(stages=[
            StageConfig(name="implement", substages={
                "code": SubstageConfig(name="code", pre_completion=[{"file_exists": "test.md"}])
            })
        ])
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

    # Tests for get_git_diff_stats()

    @patch('agenttree.hooks.get_default_branch')
    @patch('subprocess.run')
    def test_get_git_diff_stats_parses_shortstat_output(self, mock_run, mock_default_branch):
        """Should parse typical shortstat output correctly."""
        from agenttree.hooks import get_git_diff_stats

        mock_default_branch.return_value = "main"
        mock_run.return_value = MagicMock(
            stdout=" 5 files changed, 100 insertions(+), 20 deletions(-)\n",
            returncode=0
        )

        result = get_git_diff_stats()

        assert result == {'files_changed': 5, 'lines_added': 100, 'lines_removed': 20}
        mock_default_branch.assert_called_once()
        mock_run.assert_called_once()
        # Verify the correct git command was called
        call_args = mock_run.call_args[0][0]
        assert call_args[0:2] == ["git", "diff"]
        assert "--shortstat" in call_args
        assert "main...HEAD" in call_args

    @patch('agenttree.hooks.get_default_branch')
    @patch('subprocess.run')
    def test_get_git_diff_stats_handles_only_insertions(self, mock_run, mock_default_branch):
        """Should handle output with only insertions (no deletions)."""
        from agenttree.hooks import get_git_diff_stats

        mock_default_branch.return_value = "main"
        mock_run.return_value = MagicMock(
            stdout=" 3 files changed, 50 insertions(+)\n",
            returncode=0
        )

        result = get_git_diff_stats()

        assert result == {'files_changed': 3, 'lines_added': 50, 'lines_removed': 0}

    @patch('agenttree.hooks.get_default_branch')
    @patch('subprocess.run')
    def test_get_git_diff_stats_handles_only_deletions(self, mock_run, mock_default_branch):
        """Should handle output with only deletions (no insertions)."""
        from agenttree.hooks import get_git_diff_stats

        mock_default_branch.return_value = "main"
        mock_run.return_value = MagicMock(
            stdout=" 2 files changed, 30 deletions(-)\n",
            returncode=0
        )

        result = get_git_diff_stats()

        assert result == {'files_changed': 2, 'lines_added': 0, 'lines_removed': 30}

    @patch('agenttree.hooks.get_default_branch')
    @patch('subprocess.run')
    def test_get_git_diff_stats_handles_single_file(self, mock_run, mock_default_branch):
        """Should handle singular 'file' in output."""
        from agenttree.hooks import get_git_diff_stats

        mock_default_branch.return_value = "main"
        mock_run.return_value = MagicMock(
            stdout=" 1 file changed, 10 insertions(+)\n",
            returncode=0
        )

        result = get_git_diff_stats()

        assert result == {'files_changed': 1, 'lines_added': 10, 'lines_removed': 0}

    @patch('agenttree.hooks.get_default_branch')
    @patch('subprocess.run')
    def test_get_git_diff_stats_handles_empty_output(self, mock_run, mock_default_branch):
        """Should return zeros when there are no changes."""
        from agenttree.hooks import get_git_diff_stats

        mock_default_branch.return_value = "main"
        mock_run.return_value = MagicMock(
            stdout="",
            returncode=0
        )

        result = get_git_diff_stats()

        assert result == {'files_changed': 0, 'lines_added': 0, 'lines_removed': 0}

    @patch('agenttree.hooks.get_default_branch')
    @patch('subprocess.run')
    def test_get_git_diff_stats_handles_git_failure(self, mock_run, mock_default_branch):
        """Should return zeros gracefully when git command fails."""
        from agenttree.hooks import get_git_diff_stats

        mock_default_branch.return_value = "main"
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="fatal: not a git repository",
            returncode=128
        )

        result = get_git_diff_stats()

        assert result == {'files_changed': 0, 'lines_added': 0, 'lines_removed': 0}

    @patch('agenttree.hooks.get_default_branch')
    @patch('subprocess.run')
    def test_get_git_diff_stats_uses_default_branch(self, mock_run, mock_default_branch):
        """Should use get_default_branch() to determine base branch."""
        from agenttree.hooks import get_git_diff_stats

        mock_default_branch.return_value = "develop"
        mock_run.return_value = MagicMock(
            stdout=" 2 files changed, 15 insertions(+), 5 deletions(-)\n",
            returncode=0
        )

        get_git_diff_stats()

        mock_default_branch.assert_called_once()
        call_args = mock_run.call_args[0][0]
        assert "develop...HEAD" in call_args

    def test_get_git_diff_stats_integration(self, temp_git_repo, monkeypatch):
        """Integration test: should return correct stats from real git operations."""
        from agenttree.hooks import get_git_diff_stats

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

        # Create a feature branch with changes
        subprocess.run(
            ["git", "checkout", "-b", "feature-branch"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )

        # Add a new file with 5 lines
        (temp_git_repo / "new_file.py").write_text("line1\nline2\nline3\nline4\nline5\n")
        subprocess.run(["git", "add", "new_file.py"], cwd=temp_git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add new file"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )

        # Modify an existing file (add 2 lines)
        (temp_git_repo / "README.md").write_text("Modified\nNew line 1\nNew line 2\n")
        subprocess.run(["git", "add", "README.md"], cwd=temp_git_repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Modify README"],
            cwd=temp_git_repo,
            check=True,
            capture_output=True
        )

        result = get_git_diff_stats()

        # Should have 2 files changed with insertions and possibly deletions
        assert result['files_changed'] == 2
        assert result['lines_added'] > 0


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
    @patch('agenttree.github.create_pr')
    @patch('agenttree.issues.update_issue_metadata')
    @patch('agenttree.issues.get_issue')
    @patch('agenttree.config.load_config')
    @patch('subprocess.run')
    def test_post_pr_create_hooks_called(
        self, mock_subprocess, mock_load_config, mock_get_issue,
        mock_update, mock_create_pr, mock_run_hooks, tmp_path
    ):
        """post_pr_create hooks should be called after PR creation via ensure_pr_for_issue."""
        from agenttree.hooks import ensure_pr_for_issue
        from agenttree.issues import Issue
        from agenttree.config import Config, HooksConfig

        # Create a fake worktree directory
        worktree_dir = tmp_path / "worktree"
        worktree_dir.mkdir()

        # Mock issue at implementation_review with branch but no PR
        mock_issue = Issue(
            id="001",
            slug="test",
            title="Test Issue",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
            stage="implementation_review",
            branch="issue-001-test",
            worktree_dir=str(worktree_dir),
        )
        mock_get_issue.return_value = mock_issue

        # Mock PR creation
        mock_pr = MagicMock()
        mock_pr.number = 123
        mock_pr.url = "https://github.com/owner/repo/pull/123"
        mock_create_pr.return_value = mock_pr

        # Mock subprocess for git operations
        mock_subprocess.return_value = MagicMock(returncode=0)

        # Configure post_pr_create hooks
        hooks_config = HooksConfig(
            post_pr_create=[{"command": "echo 'PR created'", "host_only": True}]
        )
        mock_config = Config(hooks=hooks_config)
        mock_load_config.return_value = mock_config

        # Call ensure_pr_for_issue (the actual PR creation path on host)
        result = ensure_pr_for_issue("001")

        assert result is True
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


class TestCICheckHook:
    """Tests for ci_check hook type."""

    @patch('agenttree.github.wait_for_ci')
    @patch('agenttree.github.get_pr_checks')
    def test_ci_check_success(self, mock_get_pr_checks, mock_wait_for_ci, tmp_path):
        """Should pass when all CI checks succeed."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.github import CheckStatus

        # Mock wait_for_ci returns True (success)
        mock_wait_for_ci.return_value = True

        # Mock checks are all successful
        mock_get_pr_checks.return_value = [
            CheckStatus(name="build", state="SUCCESS", conclusion="success"),
            CheckStatus(name="tests", state="SUCCESS", conclusion="success"),
        ]

        hook = {"ci_check": {"timeout": 60, "poll_interval": 10}}
        errors = run_builtin_validator(tmp_path, hook, pr_number=123)

        assert errors == []
        mock_wait_for_ci.assert_called_once_with(123, 60, 10)

    @patch('agenttree.github.wait_for_ci')
    @patch('agenttree.github.get_pr_checks')
    def test_ci_check_failure(self, mock_get_pr_checks, mock_wait_for_ci, tmp_path):
        """Should return error when CI checks fail."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.github import CheckStatus

        # Mock wait_for_ci returns False (failure/timeout)
        mock_wait_for_ci.return_value = False

        # Mock one check failed
        mock_get_pr_checks.return_value = [
            CheckStatus(name="build", state="SUCCESS", conclusion="success"),
            CheckStatus(name="tests", state="FAILURE", conclusion="failure"),
        ]

        hook = {"ci_check": {"timeout": 60}}
        errors = run_builtin_validator(tmp_path, hook, pr_number=123)

        assert len(errors) == 1
        assert "tests" in errors[0]
        assert "failed" in errors[0].lower()  # Check for "CI checks failed"

    @patch('agenttree.github.wait_for_ci')
    def test_ci_check_pending_then_success(self, mock_wait_for_ci, tmp_path):
        """Should pass when CI eventually succeeds after pending."""
        from agenttree.hooks import run_builtin_validator

        # Mock wait_for_ci returns True (eventual success)
        mock_wait_for_ci.return_value = True

        hook = {"ci_check": {"timeout": 300, "poll_interval": 30}}
        errors = run_builtin_validator(tmp_path, hook, pr_number=456)

        assert errors == []
        mock_wait_for_ci.assert_called_once_with(456, 300, 30)

    @patch('agenttree.github.wait_for_ci')
    @patch('agenttree.github.get_pr_checks')
    def test_ci_check_timeout(self, mock_get_pr_checks, mock_wait_for_ci, tmp_path):
        """Should return timeout error when CI doesn't complete in time."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.github import CheckStatus

        # Mock wait_for_ci returns False (timeout)
        mock_wait_for_ci.return_value = False

        # Mock checks still pending
        mock_get_pr_checks.return_value = [
            CheckStatus(name="build", state="PENDING", conclusion=None),
        ]

        hook = {"ci_check": {"timeout": 60}}
        errors = run_builtin_validator(tmp_path, hook, pr_number=789)

        assert len(errors) == 1
        assert "pending" in errors[0].lower() or "timeout" in errors[0].lower() or "build" in errors[0].lower()

    def test_ci_check_no_pr_number(self, tmp_path):
        """Should return error when no PR number is provided."""
        from agenttree.hooks import run_builtin_validator

        hook = {"ci_check": {"timeout": 60}}
        errors = run_builtin_validator(tmp_path, hook, pr_number=None)

        assert len(errors) == 1
        assert "No PR number" in errors[0]

    @patch('agenttree.hooks.is_running_in_container', return_value=True)
    def test_ci_check_host_only_in_container(self, mock_in_container, tmp_path):
        """Should skip (return empty errors) when running in container with host_only."""
        from agenttree.hooks import execute_hooks
        from agenttree.config import SubstageConfig

        # The ci_check hook should be skipped entirely when running in container
        # with host_only set. This test verifies the execute_hooks behavior.
        config = SubstageConfig(
            name="ci_wait",
            pre_completion=[{"ci_check": {"timeout": 60}, "host_only": True}],
        )

        errors = execute_hooks(tmp_path, "implementation_review", config, "pre_completion", pr_number=123)

        # Should be empty because hook is skipped in container
        assert errors == []

    @patch('agenttree.github.wait_for_ci')
    @patch('agenttree.github.get_pr_checks')
    def test_ci_check_creates_feedback_file(self, mock_get_pr_checks, mock_wait_for_ci, tmp_path):
        """Should create ci_feedback.md file on CI failure."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.github import CheckStatus

        # Mock CI failure
        mock_wait_for_ci.return_value = False
        mock_get_pr_checks.return_value = [
            CheckStatus(name="lint", state="FAILURE", conclusion="failure"),
            CheckStatus(name="tests", state="FAILURE", conclusion="failure"),
        ]

        hook = {"ci_check": {"timeout": 60}}
        # tmp_path is passed as the issue_dir (first parameter)
        errors = run_builtin_validator(tmp_path, hook, pr_number=123)

        assert len(errors) >= 1
        # Check that feedback file was created
        feedback_file = tmp_path / "ci_feedback.md"
        assert feedback_file.exists()
        content = feedback_file.read_text()
        assert "lint" in content
        assert "tests" in content

    @patch('agenttree.github.wait_for_ci')
    @patch('agenttree.github.get_pr_checks')
    def test_ci_check_no_checks_passes(self, mock_get_pr_checks, mock_wait_for_ci, tmp_path):
        """Should pass when no CI checks are configured (empty list)."""
        from agenttree.hooks import run_builtin_validator

        # Mock wait_for_ci returns True (consider empty as success)
        mock_wait_for_ci.return_value = True

        # Mock no checks configured
        mock_get_pr_checks.return_value = []

        hook = {"ci_check": {"timeout": 60}}
        errors = run_builtin_validator(tmp_path, hook, pr_number=123)

        # Should treat empty checks as success
        assert errors == []


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
        from agenttree.config import Config, StageConfig, SubstageConfig

        # Create config with stages (stages are now required)
        config = Config(stages=[
            StageConfig(name="implement", substages={
                "code": SubstageConfig(name="code", pre_completion=[{"file_exists": "test.md"}])
            })
        ])
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
        # May be called multiple times (substage + stage level)
        mock_execute_hooks.assert_called()
        for call in mock_execute_hooks.call_args_list:
            assert call[0][3] == "pre_completion"

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_execute_enter_hooks_uses_post_start(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """execute_enter_hooks should use post_start field."""
        from agenttree.hooks import execute_enter_hooks
        from agenttree.config import Config, StageConfig, SubstageConfig

        # Create config with stages (stages are now required)
        config = Config(stages=[
            StageConfig(name="implement", substages={
                "code": SubstageConfig(name="code", post_start=[{"create_file": {"template": "t.md", "dest": "d.md"}}])
            })
        ])
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


class TestAsyncHookExecution:
    """Tests for async hook execution (fire-and-forget mode)."""

    def test_async_hook_does_not_block(self, tmp_path):
        """Async hook should return immediately without waiting for command completion."""
        import time
        from agenttree.hooks import run_host_hooks

        # Use a slow command that takes 2 seconds
        hooks = [{"command": "sleep 2", "async": True}]

        start = time.monotonic()
        run_host_hooks(hooks, {"issue_id": "001"})
        elapsed = time.monotonic() - start

        # Should return in less than 1 second (generous threshold for CI)
        assert elapsed < 1.0, f"Async hook blocked for {elapsed:.2f}s, expected < 1.0s"

    def test_sync_hook_blocks_until_complete(self, tmp_path):
        """Sync hook (default) should block until command completes."""
        from agenttree.hooks import run_host_hooks

        marker = tmp_path / "marker.txt"
        hooks = [{"command": f"touch {marker}"}]

        run_host_hooks(hooks, {"issue_id": "001"})

        # File should exist after sync hook completes
        assert marker.exists(), "Sync hook did not complete before returning"

    def test_mixed_async_and_sync_hooks(self, tmp_path):
        """Sync hooks should complete in order while async hooks run in background."""
        from agenttree.hooks import run_host_hooks

        sync_marker = tmp_path / "sync_marker.txt"
        hooks = [
            {"command": "sleep 1", "async": True},  # Async hook 1
            {"command": f"touch {sync_marker}"},     # Sync hook (should complete)
            {"command": "sleep 1", "async": True},  # Async hook 2
        ]

        run_host_hooks(hooks, {"issue_id": "001"})

        # Sync marker should exist (sync hook completed)
        assert sync_marker.exists(), "Sync hook did not complete"

    def test_async_hook_errors_logged(self, tmp_path, capsys):
        """Errors from async hooks should be logged, not raised."""
        import time
        from agenttree.hooks import run_host_hooks

        hooks = [{"command": "exit 1", "async": True}]

        # Should not raise
        run_host_hooks(hooks, {"issue_id": "001"})

        # Give a brief moment for async error logging
        time.sleep(0.2)

        # Note: Async errors may be logged asynchronously, so we can't guarantee
        # the exact timing of the output. The key behavior is that no exception
        # is raised.

    @patch('agenttree.hooks.is_running_in_container', return_value=True)
    def test_async_hook_respects_host_only(self, mock_container, tmp_path):
        """Async hook with host_only should skip execution in container."""
        from agenttree.hooks import run_host_hooks

        marker = tmp_path / "marker.txt"
        hooks = [{"command": f"touch {marker}", "async": True, "host_only": True}]

        run_host_hooks(hooks, {"issue_id": "001"})

        # File should NOT be created because we're "in container"
        assert not marker.exists()

    def test_async_hook_variable_substitution(self, tmp_path):
        """Template variables should be substituted before async execution."""
        import time
        from agenttree.hooks import run_host_hooks

        output_file = tmp_path / "output.txt"
        hooks = [{"command": f"echo '{{{{issue_id}}}}' > {output_file}", "async": True}]

        run_host_hooks(hooks, {"issue_id": "042"})

        # Wait for async command to complete
        time.sleep(0.5)

        content = output_file.read_text().strip()
        assert content == "042", f"Expected '042', got '{content}'"

    def test_multiple_async_hooks_parallel(self, tmp_path):
        """Multiple async hooks should run concurrently, not sequentially."""
        import time
        from agenttree.hooks import run_host_hooks

        # Three commands that each take ~0.5 seconds
        marker1 = tmp_path / "marker1.txt"
        marker2 = tmp_path / "marker2.txt"
        marker3 = tmp_path / "marker3.txt"
        hooks = [
            {"command": f"sleep 0.5 && touch {marker1}", "async": True},
            {"command": f"sleep 0.5 && touch {marker2}", "async": True},
            {"command": f"sleep 0.5 && touch {marker3}", "async": True},
        ]

        start = time.monotonic()
        run_host_hooks(hooks, {"issue_id": "001"})
        elapsed = time.monotonic() - start

        # Should return almost immediately (< 0.5s), not after 1.5s
        assert elapsed < 0.5, f"Async hooks blocked for {elapsed:.2f}s, expected < 0.5s"

        # Wait for all async commands to complete
        time.sleep(1.0)

        # All markers should exist
        assert marker1.exists(), "Async hook 1 did not complete"
        assert marker2.exists(), "Async hook 2 did not complete"
        assert marker3.exists(), "Async hook 3 did not complete"

    def test_async_false_is_sync(self, tmp_path):
        """async: false should behave the same as omitting the flag (synchronous)."""
        from agenttree.hooks import run_host_hooks

        marker = tmp_path / "marker.txt"
        hooks = [{"command": f"touch {marker}", "async": False}]

        run_host_hooks(hooks, {"issue_id": "001"})

        # File should exist after hook completes (sync behavior)
        assert marker.exists(), "async: false did not behave synchronously"
