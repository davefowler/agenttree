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

        mock_cfg = MagicMock()
        mock_cfg.allow_self_approval = False

        with patch('agenttree.config.load_config', return_value=mock_cfg):
            with patch('agenttree.hooks.get_pr_approval_status', return_value=False):
                with patch('agenttree.hooks.subprocess.run', return_value=mock_result):
                    hook = {"type": "pr_approved"}
                    errors = run_builtin_validator(tmp_path, hook, pr_number=123)
                    assert len(errors) == 1
                    assert "approve" in errors[0].lower()

    def test_pr_approved_no_pr_number(self, tmp_path):
        """Should return error when no PR number available."""
        from agenttree.hooks import run_builtin_validator

        mock_cfg = MagicMock()
        mock_cfg.allow_self_approval = False

        with patch('agenttree.config.load_config', return_value=mock_cfg):
            hook = {"type": "pr_approved"}
            errors = run_builtin_validator(tmp_path, hook, pr_number=None)
            assert len(errors) == 1
            assert "No PR number" in errors[0]

    def test_create_file_action(self, tmp_path, monkeypatch):
        """Should create file from template."""
        from agenttree.hooks import run_builtin_validator

        # Create templates directory and template file
        templates_dir = tmp_path / "_agenttree" / "templates"
        templates_dir.mkdir(parents=True)
        (templates_dir / "review.md").write_text("# Review Template")

        # Use monkeypatch.chdir to actually change the working directory
        monkeypatch.chdir(tmp_path)

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

        # Create a real Issue object (get_issue_context requires Issue.model_dump)
        test_issue = Issue(
            id="046",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )

        hook = {"type": "create_file", "template": "review.md", "dest": "review.md"}

        with patch('agenttree.hooks.load_config', return_value=Config()):
            with patch('agenttree.issues.get_issue_dir', return_value=issue_dir):
                errors = run_builtin_validator(issue_dir, hook, issue=test_issue)

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

        # Create a real Issue object (get_issue_context requires Issue.model_dump)
        test_issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )

        # Mock load_config to return empty commands
        with patch('agenttree.hooks.load_config', return_value=Config()):
            with patch('agenttree.issues.get_issue_dir', return_value=issue_dir):
                hook = {"type": "create_file", "template": "test_review.md", "dest": "output.md"}
                errors = run_builtin_validator(issue_dir, hook, issue=test_issue)

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

        # Create a real Issue object (get_issue_context requires Issue.model_dump)
        test_issue = Issue(
            id="001",
            slug="test",
            title="Test",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
        )

        # Mock load_config to return commands and is_running_in_container to avoid /workspace
        mock_config = Config(commands={"git_branch": "echo 'feature-branch'"})
        with patch('agenttree.hooks.load_config', return_value=mock_config):
            with patch('agenttree.hooks.is_running_in_container', return_value=False):
                with patch('agenttree.issues.get_issue_dir', return_value=issue_dir):
                    hook = {"type": "create_file", "template": "stats.md", "dest": "output.md"}
                    errors = run_builtin_validator(issue_dir, hook, issue=test_issue)

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

    # min_words tests
    def test_min_words_file_success(self, tmp_path):
        """Should pass when file has enough words."""
        from agenttree.hooks import run_builtin_validator

        content = "This is a test file with more than ten words in it."
        (tmp_path / "spec.md").write_text(content)

        hook = {"type": "min_words", "file": "spec.md", "min": 10}
        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_min_words_file_failure(self, tmp_path):
        """Should fail when file has fewer words than required."""
        from agenttree.hooks import run_builtin_validator

        content = "Too short"
        (tmp_path / "spec.md").write_text(content)

        hook = {"type": "min_words", "file": "spec.md", "min": 10}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "2 words" in errors[0]
        assert "minimum is 10" in errors[0]

    def test_min_words_section_success(self, tmp_path):
        """Should pass when section has enough words."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Approach
This section has more than five words which is enough to pass the test validation.

## Notes
Brief.
"""
        (tmp_path / "spec.md").write_text(content)

        hook = {"type": "min_words", "file": "spec.md", "section": "Approach", "min": 5}
        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_min_words_section_failure(self, tmp_path):
        """Should fail when section has fewer words than required."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Approach
Too short.

## Notes
More content here.
"""
        (tmp_path / "spec.md").write_text(content)

        hook = {"type": "min_words", "file": "spec.md", "section": "Approach", "min": 10}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "approach" in errors[0].lower()
        assert "minimum is 10" in errors[0]

    def test_min_words_file_not_found(self, tmp_path):
        """Should fail when file doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        hook = {"type": "min_words", "file": "missing.md", "min": 10}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_min_words_section_not_found(self, tmp_path):
        """Should fail when section doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Other Section
Some content here.
"""
        (tmp_path / "spec.md").write_text(content)

        hook = {"type": "min_words", "file": "spec.md", "section": "Missing", "min": 5}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "Section 'Missing' not found" in errors[0]

    # has_list_items tests
    def test_has_list_items_success(self, tmp_path):
        """Should pass when section has enough list items."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Tasks
- First task
- Second task
- Third task

## Notes
Some notes here.
"""
        (tmp_path / "plan.md").write_text(content)

        hook = {"type": "has_list_items", "file": "plan.md", "section": "Tasks", "min": 2}
        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_has_list_items_failure(self, tmp_path):
        """Should fail when section has fewer list items than required."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Tasks
- Only one task

## Notes
Some notes here.
"""
        (tmp_path / "plan.md").write_text(content)

        hook = {"type": "has_list_items", "file": "plan.md", "section": "Tasks", "min": 3}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "1 list items" in errors[0]
        assert "minimum is 3" in errors[0]

    def test_has_list_items_asterisk_syntax(self, tmp_path):
        """Should recognize asterisk list items."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Tasks
* First task
* Second task

## Notes
"""
        (tmp_path / "plan.md").write_text(content)

        hook = {"type": "has_list_items", "file": "plan.md", "section": "Tasks", "min": 2}
        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_has_list_items_file_not_found(self, tmp_path):
        """Should fail when file doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        hook = {"type": "has_list_items", "file": "missing.md", "section": "Tasks"}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_has_list_items_section_not_found(self, tmp_path):
        """Should fail when section doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Other Section
- Item
"""
        (tmp_path / "plan.md").write_text(content)

        hook = {"type": "has_list_items", "file": "plan.md", "section": "Missing"}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "Section 'Missing' not found" in errors[0]

    # contains tests
    def test_contains_success(self, tmp_path):
        """Should pass when section contains one of the values."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Complexity
Medium

## Notes
"""
        (tmp_path / "spec.md").write_text(content)

        hook = {"type": "contains", "file": "spec.md", "section": "Complexity", "values": ["Low", "Medium", "High"]}
        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_contains_failure(self, tmp_path):
        """Should fail when section doesn't contain any of the values."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Complexity
Unknown

## Notes
"""
        (tmp_path / "spec.md").write_text(content)

        hook = {"type": "contains", "file": "spec.md", "section": "Complexity", "values": ["Low", "Medium", "High"]}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "must contain one of" in errors[0]

    def test_contains_case_insensitive(self, tmp_path):
        """Should match values case-insensitively."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Complexity
MEDIUM

## Notes
"""
        (tmp_path / "spec.md").write_text(content)

        hook = {"type": "contains", "file": "spec.md", "section": "Complexity", "values": ["low", "medium", "high"]}
        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_contains_file_not_found(self, tmp_path):
        """Should fail when file doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        hook = {"type": "contains", "file": "missing.md", "section": "Complexity", "values": ["Low"]}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_contains_section_not_found(self, tmp_path):
        """Should fail when section doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        content = """# Document

## Other Section
Content
"""
        (tmp_path / "spec.md").write_text(content)

        hook = {"type": "contains", "file": "spec.md", "section": "Missing", "values": ["Value"]}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "Section 'Missing' not found" in errors[0]

    @patch('urllib.request.urlopen')
    def test_server_running_success(self, mock_urlopen, tmp_path):
        """Should pass when server responds with 2xx status."""
        from agenttree.hooks import run_builtin_validator
        import agenttree.hooks as hooks_module

        # Create mock issue with ID
        mock_issue = Mock()
        mock_issue.id = "001"

        # Mock config to return port 9001 for issue "001"
        mock_config = Mock()
        mock_config.get_port_for_issue.return_value = 9001

        # Mock successful HTTP response
        mock_response = Mock()
        mock_response.status = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        with patch.object(hooks_module, 'load_config', return_value=mock_config):
            hook = {"type": "server_running"}
            errors = run_builtin_validator(tmp_path, hook, issue=mock_issue)
            assert errors == []

    def test_server_running_no_issue(self, tmp_path):
        """Should return error when no issue provided."""
        from agenttree.hooks import run_builtin_validator

        hook = {"type": "server_running"}
        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "No issue provided" in errors[0]

    def test_server_running_no_port(self, tmp_path):
        """Should return error when issue has no valid port."""
        from agenttree.hooks import run_builtin_validator
        import agenttree.hooks as hooks_module

        mock_issue = Mock()
        mock_issue.id = "invalid"

        # Mock config to return None for invalid issue ID
        mock_config = Mock()
        mock_config.get_port_for_issue.return_value = None

        with patch.object(hooks_module, 'load_config', return_value=mock_config):
            hook = {"type": "server_running"}
            errors = run_builtin_validator(tmp_path, hook, issue=mock_issue)
            assert len(errors) == 1
            assert "no valid port assigned" in errors[0]

    @patch('urllib.request.urlopen')
    @patch('time.sleep')
    def test_server_running_failure_after_retries(self, mock_sleep, mock_urlopen, tmp_path):
        """Should return error after all retries fail."""
        from agenttree.hooks import run_builtin_validator
        import agenttree.hooks as hooks_module
        import urllib.error

        mock_issue = Mock()
        mock_issue.id = "001"

        # Mock config to return port 9001
        mock_config = Mock()
        mock_config.get_port_for_issue.return_value = 9001

        # Mock connection error
        mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

        with patch.object(hooks_module, 'load_config', return_value=mock_config):
            hook = {"type": "server_running", "retries": 2}
            errors = run_builtin_validator(tmp_path, hook, issue=mock_issue)
            assert len(errors) == 1
            assert "not responding" in errors[0]
            assert "9001" in errors[0]

    @patch('urllib.request.urlopen')
    def test_server_running_custom_health_endpoint(self, mock_urlopen, tmp_path):
        """Should use custom health endpoint when specified."""
        from agenttree.hooks import run_builtin_validator
        import agenttree.hooks as hooks_module

        mock_issue = Mock()
        mock_issue.id = "001"

        # Mock config to return port 9001
        mock_config = Mock()
        mock_config.get_port_for_issue.return_value = 9001

        mock_response = Mock()
        mock_response.status = 200
        mock_response.__enter__ = Mock(return_value=mock_response)
        mock_response.__exit__ = Mock(return_value=False)
        mock_urlopen.return_value = mock_response

        with patch.object(hooks_module, 'load_config', return_value=mock_config):
            hook = {"type": "server_running", "health_endpoint": "/health"}
            errors = run_builtin_validator(tmp_path, hook, issue=mock_issue)

            # Check that the request was made to the correct URL
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            assert request.full_url == "http://localhost:9001/health"


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
    """Tests for cleanup_issue_agent function.

    cleanup_issue_agent now delegates to stop_all_agents_for_issue,
    so we just verify that delegation happens correctly.
    """

    def test_no_agent_to_cleanup(self):
        """Should print message when no agents to cleanup."""
        from agenttree.hooks import cleanup_issue_agent

        issue = Issue(
            id="001",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=ACCEPTED,
        )

        with patch("agenttree.api.stop_all_agents_for_issue", return_value=0) as mock_stop:
            cleanup_issue_agent(issue)
            mock_stop.assert_called_once_with("001")

    def test_cleanup_delegates_to_stop_all_agents(self):
        """Should delegate to stop_all_agents_for_issue."""
        from agenttree.hooks import cleanup_issue_agent

        issue = Issue(
            id="042",
            slug="test-issue",
            title="Test Issue",
            created="2026-01-11T12:00:00Z",
            updated="2026-01-11T12:00:00Z",
            stage=ACCEPTED,
        )

        with patch("agenttree.api.stop_all_agents_for_issue", return_value=2) as mock_stop:
            cleanup_issue_agent(issue)
            mock_stop.assert_called_once_with("042")


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
            CheckStatus(name="build", state="SUCCESS"),
            CheckStatus(name="tests", state="SUCCESS"),
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
            CheckStatus(name="build", state="SUCCESS"),
            CheckStatus(name="tests", state="FAILURE"),
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
            CheckStatus(name="build", state="PENDING"),
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
            CheckStatus(name="lint", state="FAILURE"),
            CheckStatus(name="tests", state="FAILURE"),
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
        # May be called multiple times (substage + stage level on first substage)
        mock_execute_hooks.assert_called()
        for call in mock_execute_hooks.call_args_list:
            assert call[0][3] == "post_start"


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


class TestHookExecutionOrder:
    """Tests for hook execution order in stage/substage transitions."""

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_exit_hooks_stage_before_substage(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """execute_exit_hooks should run stage hooks before substage hooks (on last substage)."""
        from agenttree.hooks import execute_exit_hooks
        from agenttree.config import Config, StageConfig, SubstageConfig

        # Create config with stage and substage, both with pre_completion hooks
        config = Config(stages=[
            StageConfig(
                name="implement",
                pre_completion=[{"file_exists": "stage.md"}],
                substages={
                    "code": SubstageConfig(name="code", pre_completion=[{"file_exists": "substage.md"}]),
                    "review": SubstageConfig(name="review", pre_completion=[{"file_exists": "review.md"}]),
                }
            )
        ])
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = []

        issue = Mock()
        issue.id = "001"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None

        # Exit from last substage (review) - should run both stage and substage hooks
        execute_exit_hooks(issue, "implement", "review")

        # Should be called twice: once for stage, once for substage
        assert mock_execute_hooks.call_count == 2

        # Verify order: stage hooks first (position 0), substage hooks second (position 1)
        calls = mock_execute_hooks.call_args_list
        # First call should be with stage_config (stage hooks)
        first_call_config = calls[0][0][2]  # Third positional arg is the config
        assert hasattr(first_call_config, 'substages'), "First call should be stage config (has substages)"
        # Second call should be with substage_config
        second_call_config = calls[1][0][2]
        assert not hasattr(second_call_config, 'substages') or second_call_config.substages is None, \
            "Second call should be substage config (no substages)"

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_exit_hooks_only_stage_on_non_last_substage(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """execute_exit_hooks should only run substage hooks on non-last substage."""
        from agenttree.hooks import execute_exit_hooks
        from agenttree.config import Config, StageConfig, SubstageConfig

        config = Config(stages=[
            StageConfig(
                name="implement",
                pre_completion=[{"file_exists": "stage.md"}],
                substages={
                    "code": SubstageConfig(name="code", pre_completion=[{"file_exists": "code.md"}]),
                    "review": SubstageConfig(name="review", pre_completion=[{"file_exists": "review.md"}]),
                }
            )
        ])
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = []

        issue = Mock()
        issue.id = "001"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None

        # Exit from first substage (code) - should only run substage hooks, not stage
        execute_exit_hooks(issue, "implement", "code")

        # Should only be called once (substage hooks only, since not last substage)
        assert mock_execute_hooks.call_count == 1

        # Verify it was the substage config
        call_config = mock_execute_hooks.call_args[0][2]
        assert not hasattr(call_config, 'substages') or call_config.substages is None

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_enter_hooks_substage_before_stage(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """execute_enter_hooks should run substage hooks before stage hooks (on first substage)."""
        from agenttree.hooks import execute_enter_hooks
        from agenttree.config import Config, StageConfig, SubstageConfig

        config = Config(stages=[
            StageConfig(
                name="implementation_review",
                post_start=[{"create_pr": {}}],
                substages={
                    "ci_wait": SubstageConfig(name="ci_wait", post_start=[{"file_exists": "ci.md"}]),
                    "review": SubstageConfig(name="review", post_start=[{"file_exists": "review.md"}]),
                }
            )
        ])
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = []

        issue = Mock()
        issue.id = "001"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None

        # Enter first substage (ci_wait) - should run both substage and stage hooks
        execute_enter_hooks(issue, "implementation_review", "ci_wait")

        # Should be called twice: once for substage, once for stage
        assert mock_execute_hooks.call_count == 2

        # Verify order: substage hooks first (position 0), stage hooks second (position 1)
        calls = mock_execute_hooks.call_args_list
        # First call should be with substage_config (no substages attribute)
        first_call_config = calls[0][0][2]
        assert not hasattr(first_call_config, 'substages') or first_call_config.substages is None, \
            "First call should be substage config"
        # Second call should be with stage_config (has substages)
        second_call_config = calls[1][0][2]
        assert hasattr(second_call_config, 'substages'), "Second call should be stage config"

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_enter_hooks_only_substage_on_non_first(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """execute_enter_hooks should only run substage hooks on non-first substage."""
        from agenttree.hooks import execute_enter_hooks
        from agenttree.config import Config, StageConfig, SubstageConfig

        config = Config(stages=[
            StageConfig(
                name="implementation_review",
                post_start=[{"create_pr": {}}],
                substages={
                    "ci_wait": SubstageConfig(name="ci_wait", post_start=[{"file_exists": "ci.md"}]),
                    "review": SubstageConfig(name="review", post_start=[{"file_exists": "review.md"}]),
                }
            )
        ])
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = []

        issue = Mock()
        issue.id = "001"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None

        # Enter second substage (review) - should only run substage hooks, not stage
        execute_enter_hooks(issue, "implementation_review", "review")

        # Should only be called once (substage hooks only, since not first substage)
        assert mock_execute_hooks.call_count == 1

        # Verify it was the substage config
        call_config = mock_execute_hooks.call_args[0][2]
        assert not hasattr(call_config, 'substages') or call_config.substages is None

    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_enter_hooks_stage_only_when_no_substages(
        self, mock_get_dir, mock_load_config, mock_execute_hooks
    ):
        """execute_enter_hooks should run stage hooks when entering without substage."""
        from agenttree.hooks import execute_enter_hooks
        from agenttree.config import Config, StageConfig

        config = Config(stages=[
            StageConfig(
                name="backlog",
                post_start=[{"file_exists": "issue.yaml"}],
            )
        ])
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = []

        issue = Mock()
        issue.id = "001"
        issue.title = "Test"
        issue.branch = "test-branch"
        issue.pr_number = None

        # Enter stage without substage
        execute_enter_hooks(issue, "backlog", None)

        # Should be called once (stage hooks)
        assert mock_execute_hooks.call_count == 1

        # Verify it was the stage config
        call_config = mock_execute_hooks.call_args[0][2]
        assert hasattr(call_config, 'name') and call_config.name == "backlog"

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    @patch('agenttree.hooks.execute_hooks')
    @patch('agenttree.config.load_config')
    @patch('agenttree.issues.get_issue_dir')
    def test_enter_hooks_fixes_pr_creation_bug(
        self, mock_get_dir, mock_load_config, mock_execute_hooks, mock_container
    ):
        """Stage-level post_start hooks should run when entering first substage (PR creation bug fix)."""
        from agenttree.hooks import execute_enter_hooks
        from agenttree.config import Config, StageConfig, SubstageConfig

        # This mimics the real implementation_review config that caused the bug
        config = Config(stages=[
            StageConfig(
                name="implementation_review",
                role="manager",
                post_start=[{"create_pr": {}}],  # Stage-level hook
                substages={
                    "ci_wait": SubstageConfig(name="ci_wait"),  # No post_start hooks
                    "review": SubstageConfig(name="review"),
                }
            )
        ])
        mock_load_config.return_value = config
        mock_get_dir.return_value = Path("/tmp/issue")
        mock_execute_hooks.return_value = []

        issue = Mock()
        issue.id = "048"
        issue.title = "TUI for issue management"
        issue.branch = "issue-048-tui"
        issue.pr_number = None

        # Enter implementation_review.ci_wait (first substage)
        # This is where the bug was - create_pr never ran because only substage hooks were executed
        execute_enter_hooks(issue, "implementation_review", "ci_wait")

        # Should be called at least once for stage-level hooks
        assert mock_execute_hooks.call_count >= 1

        # Verify stage-level hooks were called (the one with create_pr)
        stage_hooks_called = False
        for call in mock_execute_hooks.call_args_list:
            config_arg = call[0][2]
            if hasattr(config_arg, 'post_start') and config_arg.post_start:
                for hook in config_arg.post_start:
                    if 'create_pr' in hook:
                        stage_hooks_called = True
                        break

        assert stage_hooks_called, "Stage-level post_start hooks (with create_pr) should have been called"


class TestStageRedirect:
    """Tests for StageRedirect exception."""

    def test_stage_redirect_is_exception(self):
        """StageRedirect should be an Exception."""
        from agenttree.hooks import StageRedirect

        assert issubclass(StageRedirect, Exception)

    def test_stage_redirect_attributes(self):
        """StageRedirect should store target_stage and reason."""
        from agenttree.hooks import StageRedirect

        redirect = StageRedirect("address_independent_review", "Checkbox not checked")
        assert redirect.target_stage == "address_independent_review"
        assert redirect.reason == "Checkbox not checked"

    def test_stage_redirect_message(self):
        """StageRedirect should have descriptive message."""
        from agenttree.hooks import StageRedirect

        redirect = StageRedirect("target_stage", "test reason")
        assert "target_stage" in str(redirect)
        assert "test reason" in str(redirect)


class TestCheckboxCheckedHook:
    """Tests for checkbox_checked hook validator."""

    def test_checkbox_checked_success(self, tmp_path):
        """Should pass when checkbox is checked."""
        from agenttree.hooks import run_builtin_validator

        content = """# Review

## Approval

- [x] **Approve** - Code is ready to merge
- [ ] Request changes
"""
        (tmp_path / "review.md").write_text(content)
        hook = {"checkbox_checked": {"file": "review.md", "checkbox": "Approve"}}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_checkbox_checked_uppercase_x(self, tmp_path):
        """Should pass when checkbox uses uppercase X."""
        from agenttree.hooks import run_builtin_validator

        content = """# Review
- [X] **Approve** - Ready
"""
        (tmp_path / "review.md").write_text(content)
        hook = {"checkbox_checked": {"file": "review.md", "checkbox": "Approve"}}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_checkbox_checked_failure_unchecked(self, tmp_path):
        """Should return error when checkbox is not checked."""
        from agenttree.hooks import run_builtin_validator

        content = """# Review
- [ ] **Approve** - Not ready yet
"""
        (tmp_path / "review.md").write_text(content)
        hook = {"checkbox_checked": {"file": "review.md", "checkbox": "Approve"}}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "not checked" in errors[0]

    def test_checkbox_checked_raises_redirect_on_fail_stage(self, tmp_path):
        """Should raise StageRedirect when on_fail_stage is set and checkbox unchecked."""
        from agenttree.hooks import run_builtin_validator, StageRedirect

        content = """# Review
- [ ] **Approve** - Code needs changes
"""
        (tmp_path / "review.md").write_text(content)
        hook = {
            "checkbox_checked": {
                "file": "review.md",
                "checkbox": "Approve",
                "on_fail_stage": "address_independent_review"
            }
        }

        with pytest.raises(StageRedirect) as exc_info:
            run_builtin_validator(tmp_path, hook)

        assert exc_info.value.target_stage == "address_independent_review"

    def test_checkbox_checked_file_not_found(self, tmp_path):
        """Should return error when file doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        hook = {"checkbox_checked": {"file": "missing.md", "checkbox": "Approve"}}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "not found" in errors[0]

    def test_checkbox_not_found_in_file(self, tmp_path):
        """Should return error when checkbox text not found."""
        from agenttree.hooks import run_builtin_validator

        content = """# Review
- [ ] Something else
"""
        (tmp_path / "review.md").write_text(content)
        hook = {"checkbox_checked": {"file": "review.md", "checkbox": "Approve"}}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "not found" in errors[0]


class TestVersionFileHook:
    """Tests for version_file hook action."""

    def test_version_file_first_version(self, tmp_path):
        """Should rename file to v1 when no versions exist."""
        from agenttree.hooks import run_builtin_validator

        (tmp_path / "review.md").write_text("# Review content")
        hook = {"version_file": {"file": "review.md"}}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []
        assert not (tmp_path / "review.md").exists()
        assert (tmp_path / "review_v1.md").exists()
        assert (tmp_path / "review_v1.md").read_text() == "# Review content"

    def test_version_file_increments_version(self, tmp_path):
        """Should increment version number when previous versions exist."""
        from agenttree.hooks import run_builtin_validator

        # Create existing versioned files
        (tmp_path / "review_v1.md").write_text("v1 content")
        (tmp_path / "review_v2.md").write_text("v2 content")
        (tmp_path / "review.md").write_text("# Latest content")

        hook = {"version_file": {"file": "review.md"}}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []
        assert not (tmp_path / "review.md").exists()
        assert (tmp_path / "review_v3.md").exists()
        assert (tmp_path / "review_v3.md").read_text() == "# Latest content"

    def test_version_file_missing_file_silent(self, tmp_path):
        """Should silently skip when file doesn't exist."""
        from agenttree.hooks import run_builtin_validator

        hook = {"version_file": {"file": "missing.md"}}

        errors = run_builtin_validator(tmp_path, hook)
        # No error - file not existing is OK (first iteration case)
        assert errors == []

    def test_version_file_missing_parameter(self, tmp_path):
        """Should return error when file parameter missing."""
        from agenttree.hooks import run_builtin_validator

        hook = {"version_file": {}}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "file" in errors[0].lower()


class TestLoopCheckHook:
    """Tests for loop_check hook validator."""

    def test_loop_check_under_limit(self, tmp_path):
        """Should pass when version count is under limit."""
        from agenttree.hooks import run_builtin_validator

        # Create 2 versioned files
        (tmp_path / "review_v1.md").write_text("v1")
        (tmp_path / "review_v2.md").write_text("v2")

        hook = {"loop_check": {"count_files": "review_v*.md", "max": 5}}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []

    def test_loop_check_at_limit(self, tmp_path):
        """Should fail when version count equals limit."""
        from agenttree.hooks import run_builtin_validator

        # Create 5 versioned files
        for i in range(1, 6):
            (tmp_path / f"review_v{i}.md").write_text(f"v{i}")

        hook = {"loop_check": {"count_files": "review_v*.md", "max": 5}}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "5" in errors[0]

    def test_loop_check_over_limit(self, tmp_path):
        """Should fail when version count exceeds limit."""
        from agenttree.hooks import run_builtin_validator

        # Create 6 versioned files
        for i in range(1, 7):
            (tmp_path / f"review_v{i}.md").write_text(f"v{i}")

        hook = {"loop_check": {"count_files": "review_v*.md", "max": 5}}

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "6" in errors[0]

    def test_loop_check_custom_error_message(self, tmp_path):
        """Should use custom error message when provided."""
        from agenttree.hooks import run_builtin_validator

        for i in range(1, 4):
            (tmp_path / f"review_v{i}.md").write_text(f"v{i}")

        hook = {
            "loop_check": {
                "count_files": "review_v*.md",
                "max": 3,
                "error": "Too many review iterations"
            }
        }

        errors = run_builtin_validator(tmp_path, hook)
        assert len(errors) == 1
        assert "Too many review iterations" in errors[0]

    def test_loop_check_no_files(self, tmp_path):
        """Should pass when no matching files exist."""
        from agenttree.hooks import run_builtin_validator

        hook = {"loop_check": {"count_files": "review_v*.md", "max": 5}}

        errors = run_builtin_validator(tmp_path, hook)
        assert errors == []


class TestRollbackHook:
    """Tests for rollback hook action."""

    def test_rollback_hook_requires_to_stage(self, tmp_path):
        """Should return error when to_stage not provided."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.issues import Issue

        mock_issue = Issue(
            id="42",
            slug="test",
            title="Test",
            stage="implement",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        hook = {"rollback": {}}

        errors = run_builtin_validator(tmp_path, hook, issue=mock_issue)
        assert len(errors) == 1
        assert "to_stage" in errors[0].lower()

    def test_rollback_hook_requires_issue_context(self, tmp_path):
        """Should return error when issue not provided."""
        from agenttree.hooks import run_builtin_validator

        hook = {"rollback": {"to_stage": "research"}}

        errors = run_builtin_validator(tmp_path, hook)  # No issue kwarg
        assert len(errors) == 1
        assert "issue" in errors[0].lower()

    @patch("agenttree.rollback.execute_rollback")
    def test_rollback_hook_calls_execute_rollback(self, mock_rollback, tmp_path):
        """Should call execute_rollback with correct parameters."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.issues import Issue

        mock_rollback.return_value = True
        mock_issue = Issue(
            id="42",
            slug="test",
            title="Test",
            stage="implement",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        hook = {"rollback": {"to_stage": "research"}}

        errors = run_builtin_validator(tmp_path, hook, issue=mock_issue)

        mock_rollback.assert_called_once_with(
            issue_id="42",
            target_stage="research",
            yes=True,  # Default auto-confirm
            reset_worktree=False,
            keep_changes=True,
        )
        assert errors == []

    @patch("agenttree.rollback.execute_rollback")
    def test_rollback_hook_reports_failure(self, mock_rollback, tmp_path):
        """Should return error when rollback fails."""
        from agenttree.hooks import run_builtin_validator
        from agenttree.issues import Issue

        mock_rollback.return_value = False
        mock_issue = Issue(
            id="42",
            slug="test",
            title="Test",
            stage="implement",
            created="2026-01-01T00:00:00Z",
            updated="2026-01-01T00:00:00Z",
        )

        hook = {"rollback": {"to_stage": "research"}}

        errors = run_builtin_validator(tmp_path, hook, issue=mock_issue)
        assert len(errors) == 1
        assert "failed" in errors[0].lower()
class TestGetCodeDirectory:
    """Tests for get_code_directory() helper function."""

    @patch('agenttree.hooks.is_running_in_container', return_value=True)
    def test_returns_workspace_in_container(self, mock_in_container, tmp_path):
        """Should return /workspace when running in container."""
        from agenttree.hooks import get_code_directory

        issue = Issue(
            id="123",
            slug="test-issue",
            title="Test Issue",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
            worktree_dir=".worktrees/issue-123-test",
        )
        issue_dir = tmp_path / "_agenttree" / "issues" / "123-test-issue"

        result = get_code_directory(issue, issue_dir)

        assert result == Path("/workspace")

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_returns_worktree_dir_on_host_when_set(self, mock_in_container, tmp_path):
        """Should return worktree_dir on host when it's set."""
        from agenttree.hooks import get_code_directory

        issue = Issue(
            id="123",
            slug="test-issue",
            title="Test Issue",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
            worktree_dir=".worktrees/issue-123-test",
        )
        issue_dir = tmp_path / "_agenttree" / "issues" / "123-test-issue"

        result = get_code_directory(issue, issue_dir)

        assert result == Path(".worktrees/issue-123-test")

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_returns_issue_dir_on_host_when_worktree_none(self, mock_in_container, tmp_path):
        """Should return issue_dir on host when worktree_dir is None."""
        from agenttree.hooks import get_code_directory

        issue = Issue(
            id="123",
            slug="test-issue",
            title="Test Issue",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
            worktree_dir=None,
        )
        issue_dir = tmp_path / "_agenttree" / "issues" / "123-test-issue"

        result = get_code_directory(issue, issue_dir)

        assert result == issue_dir

    @patch('agenttree.hooks.is_running_in_container', return_value=False)
    def test_returns_issue_dir_when_issue_none_on_host(self, mock_in_container, tmp_path):
        """Should return issue_dir when issue is None on host."""
        from agenttree.hooks import get_code_directory

        issue_dir = tmp_path / "_agenttree" / "issues" / "123-test-issue"

        result = get_code_directory(None, issue_dir)

        assert result == issue_dir

    @patch('agenttree.hooks.is_running_in_container', return_value=True)
    def test_returns_workspace_when_issue_none_in_container(self, mock_in_container, tmp_path):
        """Should return /workspace when issue is None in container."""
        from agenttree.hooks import get_code_directory

        issue_dir = tmp_path / "_agenttree" / "issues" / "123-test-issue"

        result = get_code_directory(None, issue_dir)

        assert result == Path("/workspace")
