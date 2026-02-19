"""Integration tests for the independent code review loop.

Tests the full flow:
1. independent_code_review → (approved) → implement.review
2. independent_code_review → (not approved) → address_independent_review
3. address_independent_review → rollback → independent_code_review
4. max_rollbacks enforcement
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from agenttree.hooks import execute_hooks, StageRedirect, ValidationError
from agenttree.config import load_config


@pytest.fixture
def review_loop_config() -> dict:
    """Config with independent_code_review and address_independent_review stages."""
    return {
        "default_tool": "claude",
        "default_model": "opus",
        "port_range": "9001-9099",
        "project": "test-project",
        "worktrees_dir": ".worktrees",
        "roles": {
            "manager": {"description": "Human manager"},
            "agent": {"description": "Default agent"},
            "review": {"description": "Review agent", "skill": "agents/review.md"},
        },
        "flows": {
            "default": {
                "stages": {
                    "backlog": {},
                    "implement": {
                        "substages": {
                            "code": {},
                            "feedback": {},
                        },
                    },
                    "independent_code_review": {
                        "role": "review",
                        "output": "independent_review.md",
                        "pre_completion": [
                            {"file_exists": "independent_review.md"},
                            {"section_check": {"file": "independent_review.md", "section": "Review Findings", "expect": "not_empty"}},
                            {"checkbox_checked": {"file": "independent_review.md", "checkbox": "Approve", "on_fail": "address_independent_review"}},
                        ],
                    },
                    "address_independent_review": {
                        "redirect_only": True,
                        "role": "agent",
                        "output": "independent_review_response.md",
                        "pre_completion": [
                            {"section_check": {"file": "independent_review_response.md", "section": "Changes Made", "expect": "not_empty"}},
                        ],
                        "post_completion": [
                            {"rollback": {"to": "independent_code_review", "max_rollbacks": 3}},
                        ],
                    },
                    "implementation_review": {
                        "human_review": True,
                        "role": "manager",
                    },
                    "accepted": {
                        "is_parking_lot": True,
                    },
                },
            },
        },
        "default_flow": "default",
    }


@pytest.fixture
def review_loop_repo(git_repo: Path, review_loop_config: dict) -> Path:
    """Create a repo with review loop stages configured."""
    # Write config
    config_path = git_repo / ".agenttree.yaml"
    with open(config_path, "w") as f:
        yaml.dump(review_loop_config, f, default_flow_style=False, sort_keys=False)

    # Create _agenttree directory structure
    agenttree_dir = git_repo / "_agenttree"
    (agenttree_dir / "issues").mkdir(parents=True)
    (agenttree_dir / "templates").mkdir(parents=True)
    (agenttree_dir / "skills" / "agents").mkdir(parents=True)

    # Create review skill template
    (agenttree_dir / "skills" / "agents" / "review.md").write_text(
        "# Review Instructions\n\nReview the code.\n"
    )

    # Create independent_review_response template
    (agenttree_dir / "templates" / "independent_review_response.md").write_text(
        "# Response\n\n## Changes Made\n\n<!-- Describe changes -->\n"
    )

    return git_repo


def create_approved_review(issue_dir: Path) -> None:
    """Create an independent_review.md with Approve checkbox checked."""
    content = """# Independent Code Review

## Review Findings

The implementation looks good.

### Spec Compliance
Matches the spec.

### Code Quality
Clean code.

## Recommendation

[X] **Approve** - Ready for human review
[ ] **Request Changes** - Issues must be addressed first
"""
    (issue_dir / "independent_review.md").write_text(content)


def create_rejected_review(issue_dir: Path) -> None:
    """Create an independent_review.md WITHOUT Approve checkbox checked."""
    content = """# Independent Code Review

## Review Findings

Found some issues that need fixing.

### Spec Compliance
Missing a required feature.

### Code Quality
Some slop detected.

## Recommendation

[ ] **Approve** - Ready for human review
[X] **Request Changes** - Issues must be addressed first

### If Requesting Changes
- Fix the missing feature
- Remove the sloppy code
"""
    (issue_dir / "independent_review.md").write_text(content)


def create_review_response(issue_dir: Path) -> None:
    """Create an independent_review_response.md with changes documented."""
    content = """# Response to Independent Code Review

## Changes Made

- Fixed the missing feature
- Removed the sloppy code
- Added tests

## Verification

- [x] All requested changes addressed
- [x] Tests still pass
"""
    (issue_dir / "independent_review_response.md").write_text(content)


class TestCheckboxApprovalFlow:
    """Test the checkbox_checked hook approval flow."""

    def test_approved_review_passes(self, review_loop_repo: Path):
        """When Approve checkbox is checked, pre_completion passes."""
        from agenttree.issues import create_issue

        agenttree_path = review_loop_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=review_loop_repo / ".agenttree.yaml"):
                issue = create_issue(title="Test Approved Review")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                create_approved_review(issue_dir)

                config = load_config()
                stage_config = config.get_stage("independent_code_review")

                # Should not raise - approval passes
                errors = execute_hooks(issue_dir, "independent_code_review", stage_config, "pre_completion")
                assert errors == []

    def test_rejected_review_raises_redirect(self, review_loop_repo: Path):
        """When Approve checkbox is NOT checked, StageRedirect is raised."""
        from agenttree.issues import create_issue

        agenttree_path = review_loop_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=review_loop_repo / ".agenttree.yaml"):
                issue = create_issue(title="Test Rejected Review")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                create_rejected_review(issue_dir)

                config = load_config()
                stage_config = config.get_stage("independent_code_review")

                # Should raise StageRedirect
                with pytest.raises(StageRedirect) as exc_info:
                    execute_hooks(issue_dir, "independent_code_review", stage_config, "pre_completion")

<<<<<<< HEAD
                # Hook resolution prefixes relative targets with current stage
=======
                # The target gets resolved to full dot path
>>>>>>> origin/main
                assert exc_info.value.target == "independent_code_review.address_independent_review"
                assert "Approve" in exc_info.value.reason


class TestRedirectOnlyStage:
    """Test that redirect_only stages are skipped in normal progression."""

    def test_redirect_only_skipped_in_get_next_stage(self, review_loop_repo: Path):
        """get_next_stage skips redirect_only stages."""
        with patch("agenttree.config.find_config_file", return_value=review_loop_repo / ".agenttree.yaml"):
            config = load_config()

            # From independent_code_review, next should be implementation_review
            # (skipping address_independent_review which is redirect_only)
            next_stage, is_review = config.get_next_stage("independent_code_review")

            assert next_stage == "implementation_review"


class TestFullReviewLoop:
    """Test the complete review loop flow."""

    def test_full_rejection_loop_flow(self, review_loop_repo: Path):
        """Test: reject → address → (would rollback) → re-review."""
        from agenttree.issues import create_issue

        agenttree_path = review_loop_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=review_loop_repo / ".agenttree.yaml"):
                issue = create_issue(title="Test Full Loop")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"
                config = load_config()

                # Step 1: Reviewer rejects
                create_rejected_review(issue_dir)

                # Step 2: Try to advance - should redirect
                stage_config = config.get_stage("independent_code_review")
                with pytest.raises(StageRedirect) as exc_info:
                    execute_hooks(issue_dir, "independent_code_review", stage_config, "pre_completion")
<<<<<<< HEAD
                # Hook resolution prefixes relative targets with current stage
=======
                # The target gets resolved to full dot path
>>>>>>> origin/main
                assert exc_info.value.target == "independent_code_review.address_independent_review"

                # Step 3: Implementer addresses feedback
                create_review_response(issue_dir)

                # Step 4: Pre-completion should pass
                stage_config = config.get_stage("address_independent_review")
                errors = execute_hooks(issue_dir, "address_independent_review", stage_config, "pre_completion")
                assert errors == []

                # Step 5: After rollback, create new approved review
                create_approved_review(issue_dir)

                # Step 6: Now independent_code_review should pass
                stage_config = config.get_stage("independent_code_review")
                errors = execute_hooks(issue_dir, "independent_code_review", stage_config, "pre_completion")
                assert errors == []
