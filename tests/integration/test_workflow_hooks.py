"""Integration tests for hook validation in workflow context.

Tests that hooks properly block transitions when content is invalid.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agenttree.ids import format_issue_id

from tests.integration.helpers import (
    create_valid_problem_md,
    create_valid_research_md,
    create_valid_spec_md,
    create_valid_spec_review_md,
    create_valid_review_md,
    create_failing_review_md,
)


class TestDefineStageValidation:
    """Test explore.define stage validation hooks."""

    def test_blocks_without_context_section(self, workflow_repo: Path, mock_sync: MagicMock):
        """Define stage should block if Context section is empty."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Empty Context")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create problem.md with empty Context
                    content = """# Problem

## Context

<!-- Empty context - should fail -->

## Possible Solutions

- Solution 1
"""
                    (issue_dir / "problem.md").write_text(content)

                    config = load_config()
                    _, substage_config = config.resolve_stage("explore.define")

                    errors = execute_hooks(issue_dir, "explore.define", substage_config, "pre_completion")

                    assert len(errors) > 0
                    assert any("context" in e.lower() or "empty" in e.lower() for e in errors)

    def test_passes_with_valid_problem(self, workflow_repo: Path, mock_sync: MagicMock):
        """Define stage should pass with valid problem.md."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Valid Context")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    create_valid_problem_md(issue_dir)

                    config = load_config()
                    _, substage_config = config.resolve_stage("explore.define")

                    errors = execute_hooks(issue_dir, "explore.define", substage_config, "pre_completion")

                    assert errors == []


class TestResearchStageValidation:
    """Test explore.research stage validation hooks."""

    def test_blocks_without_relevant_files(self, workflow_repo: Path, mock_sync: MagicMock):
        """Research stage should block if Relevant Files section is empty."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Empty Relevant Files")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create research.md with empty Relevant Files
                    content = """# Research

## Relevant Files

<!-- No files listed -->

## Existing Patterns

Some patterns here.
"""
                    (issue_dir / "research.md").write_text(content)

                    config = load_config()
                    _, substage_config = config.resolve_stage("explore.research")

                    errors = execute_hooks(issue_dir, "explore.research", substage_config, "pre_completion")

                    assert len(errors) > 0

    def test_passes_with_valid_research(self, workflow_repo: Path, mock_sync: MagicMock):
        """Research stage should pass with valid research.md."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Valid Research")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    create_valid_research_md(issue_dir)

                    config = load_config()
                    _, substage_config = config.resolve_stage("explore.research")

                    errors = execute_hooks(issue_dir, "explore.research", substage_config, "pre_completion")

                    assert errors == []


class TestPlanStageValidation:
    """Test plan.draft stage validation hooks."""

    def test_blocks_without_approach(self, workflow_repo: Path, mock_sync: MagicMock):
        """Plan stage should block if Approach section is empty."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Empty Approach")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create spec.md with empty Approach
                    content = """# Specification

## Approach

<!-- Empty -->

## Files to Modify

- file1.py

## Implementation Steps

1. Step 1

## Test Plan

Test here.
"""
                    (issue_dir / "spec.md").write_text(content)

                    config = load_config()
                    _, substage_config = config.resolve_stage("plan.draft")

                    errors = execute_hooks(issue_dir, "plan.draft", substage_config, "pre_completion")

                    assert len(errors) > 0
                    assert any("approach" in e.lower() or "empty" in e.lower() for e in errors)

    def test_passes_with_valid_spec(self, workflow_repo: Path, mock_sync: MagicMock):
        """Plan stage should pass with valid spec.md."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Valid Spec")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    create_valid_spec_md(issue_dir)

                    config = load_config()
                    _, substage_config = config.resolve_stage("plan.draft")

                    errors = execute_hooks(issue_dir, "plan.draft", substage_config, "pre_completion")

                    assert errors == []


class TestPlanReviewValidation:
    """Test plan.review stage validation hooks."""

    def test_blocks_without_spec_file(self, workflow_repo: Path, mock_sync: MagicMock):
        """Plan review should block if spec.md doesn't exist."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Missing Spec")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Don't create spec.md

                    config = load_config()
                    _, substage_config = config.resolve_stage("plan.review")

                    errors = execute_hooks(issue_dir, "plan.review", substage_config, "pre_completion")

                    assert len(errors) > 0
                    assert any("spec.md" in e.lower() or "not exist" in e.lower() for e in errors)


class TestImplementCodeReviewValidation:
    """Test implement.code_review substage validation."""

    def test_blocks_with_unchecked_items(self, workflow_repo: Path, mock_sync: MagicMock):
        """Code review should block if checklist items are unchecked."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Unchecked Items")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    create_failing_review_md(issue_dir, reason="unchecked")

                    config = load_config()
                    _, substage_config = config.resolve_stage("implement.code_review")

                    errors = execute_hooks(issue_dir, "implement.code_review", substage_config, "pre_completion")

                    assert len(errors) > 0

    def test_passes_with_all_checked(self, workflow_repo: Path, mock_sync: MagicMock):
        """Code review should pass if all checklist items are checked."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test All Checked")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    create_valid_review_md(issue_dir)

                    config = load_config()
                    _, substage_config = config.resolve_stage("implement.code_review")

                    errors = execute_hooks(issue_dir, "implement.code_review", substage_config, "pre_completion")

                    assert errors == []


class TestImplementWrapupValidation:
    """Test implement.wrapup substage validation."""

    def test_blocks_with_low_score(self, workflow_repo: Path, mock_sync: MagicMock):
        """Wrapup should block if average score < 7."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Low Score")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    create_failing_review_md(issue_dir, reason="low_score")

                    config = load_config()
                    _, substage_config = config.resolve_stage("implement.wrapup")

                    errors = execute_hooks(issue_dir, "implement.wrapup", substage_config, "pre_completion")

                    assert len(errors) > 0
                    assert any("7" in e or "average" in e.lower() or "minimum" in e.lower() for e in errors)

    def test_passes_with_score_7(self, workflow_repo: Path, mock_sync: MagicMock):
        """Wrapup should pass if average score == 7."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Score 7")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    create_valid_review_md(issue_dir, average=7.0)

                    config = load_config()
                    _, substage_config = config.resolve_stage("implement.wrapup")

                    errors = execute_hooks(issue_dir, "implement.wrapup", substage_config, "pre_completion")

                    assert errors == []

    def test_passes_with_score_above_7(self, workflow_repo: Path, mock_sync: MagicMock):
        """Wrapup should pass if average score > 7."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Score 9")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    create_valid_review_md(issue_dir, average=9.0)

                    config = load_config()
                    _, substage_config = config.resolve_stage("implement.wrapup")

                    errors = execute_hooks(issue_dir, "implement.wrapup", substage_config, "pre_completion")

                    assert errors == []


class TestImplementFeedbackValidation:
    """Test implement.feedback substage validation."""

    def test_blocks_without_commits(self, workflow_repo: Path, mock_sync: MagicMock):
        """Feedback should block if no commits to push."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    with patch("agenttree.hooks.has_commits_to_push", return_value=False):
                        issue = create_issue(title="Test No Commits")
                        issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                        create_valid_review_md(issue_dir)

                        config = load_config()
                        _, substage_config = config.resolve_stage("implement.feedback")

                        errors = execute_hooks(issue_dir, "implement.feedback", substage_config, "pre_completion")

                        assert len(errors) > 0
                        assert any("commit" in e.lower() for e in errors)

    def test_blocks_with_critical_issues(self, workflow_repo: Path, mock_sync: MagicMock):
        """Feedback should block if Critical Issues section is not empty."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    with patch("agenttree.hooks.has_commits_to_push", return_value=True):
                        issue = create_issue(title="Test Critical Issues")
                        issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                        create_failing_review_md(issue_dir, reason="critical_issues")

                        config = load_config()
                        _, substage_config = config.resolve_stage("implement.feedback")

                        errors = execute_hooks(issue_dir, "implement.feedback", substage_config, "pre_completion")

                        assert len(errors) > 0

    def test_passes_with_commits_and_no_critical_issues(self, workflow_repo: Path, mock_sync: MagicMock):
        """Feedback should pass with commits and empty Critical Issues."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    with patch("agenttree.hooks.has_commits_to_push", return_value=True):
                        issue = create_issue(title="Test Valid Feedback")
                        issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                        create_valid_review_md(issue_dir)

                        config = load_config()
                        _, substage_config = config.resolve_stage("implement.feedback")

                        errors = execute_hooks(issue_dir, "implement.feedback", substage_config, "pre_completion")

                        assert errors == []


class TestSectionCheckVariants:
    """Test section_check hook with different header levels."""

    def test_accepts_h2_headers(self, workflow_repo: Path, mock_sync: MagicMock):
        """Section check should accept ## headers."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test H2 Headers")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create problem.md with ## Context
                    content = """# Problem

## Context

This is the context section with content.

## Possible Solutions

- Solution 1
"""
                    (issue_dir / "problem.md").write_text(content)

                    config = load_config()
                    _, substage_config = config.resolve_stage("explore.define")

                    errors = execute_hooks(issue_dir, "explore.define", substage_config, "pre_completion")

                    assert errors == []

    def test_accepts_h3_subsections(self, workflow_repo: Path, mock_sync: MagicMock):
        """Section check should accept h2 headers with h3 subsections."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test H3 Headers")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create problem.md with ## sections (section_check looks for h2 headers)
                    content = """# Problem

## Context

This is the context section with content.

### Subsection

More details here.

## Possible Solutions

- Solution 1
"""
                    (issue_dir / "problem.md").write_text(content)

                    config = load_config()
                    _, substage_config = config.resolve_stage("explore.define")

                    errors = execute_hooks(issue_dir, "explore.define", substage_config, "pre_completion")

                    assert errors == []


class TestMultipleHookErrors:
    """Test that multiple hook errors are collected."""

    def test_collects_all_errors(self, workflow_repo: Path, mock_sync: MagicMock):
        """Should collect errors from multiple failing hooks."""
        from agenttree.issues import create_issue
        from agenttree.hooks import execute_hooks
        from agenttree.config import load_config

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
                    issue = create_issue(title="Test Multiple Errors")
                    issue_dir = agenttree_path / "issues" / format_issue_id(issue.id)

                    # Create spec.md with multiple empty sections
                    content = """# Specification

## Approach

<!-- Empty -->

## Files to Modify

<!-- Empty - no list items -->

## Implementation Steps

<!-- Empty - no list items -->

## Test Plan

<!-- Empty -->
"""
                    (issue_dir / "spec.md").write_text(content)

                    config = load_config()
                    _, substage_config = config.resolve_stage("plan.draft")

                    errors = execute_hooks(issue_dir, "plan.draft", substage_config, "pre_completion")

                    # Should have multiple errors
                    assert len(errors) >= 2, f"Expected multiple errors, got: {errors}"
