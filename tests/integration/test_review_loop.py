"""Integration tests for the independent code review loop.

Tests the full flow:
1. independent_code_review → (approved) → implement.review
2. independent_code_review → (not approved) → address_independent_review
3. address_independent_review → rollback → independent_code_review
4. Version file creation during loop
5. Loop limit enforcement
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
                        "post_start": [
                            {"version_file": {"file": "independent_review.md"}},
                            {"version_file": {"file": "independent_review_response.md"}},
                        ],
                        "pre_completion": [
                            {"loop_check": {"count_files": "independent_review_v*.md", "max": 3, "error": "Review loop exceeded 3 iterations"}},
                            {"section_check": {"file": "independent_review_response.md", "section": "Changes Made", "expect": "not_empty"}},
                        ],
                        "post_completion": [
                            {"rollback": {"to": "independent_code_review"}},
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

                assert exc_info.value.target == "address_independent_review"
                assert "Approve" in exc_info.value.reason


class TestVersionFileHook:
    """Test the version_file hook creates versioned files."""

    def test_version_file_creates_v1(self, review_loop_repo: Path):
        """First version_file call creates _v1 file."""
        from agenttree.issues import create_issue

        agenttree_path = review_loop_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=review_loop_repo / ".agenttree.yaml"):
                issue = create_issue(title="Test Version File")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                # Create original file
                create_rejected_review(issue_dir)
                assert (issue_dir / "independent_review.md").exists()

                config = load_config()
                stage_config = config.get_stage("address_independent_review")

                # Execute post_start hooks (which include version_file)
                errors = execute_hooks(issue_dir, "address_independent_review", stage_config, "post_start")
                assert errors == []

                # Original should be renamed to _v1
                assert not (issue_dir / "independent_review.md").exists()
                assert (issue_dir / "independent_review_v1.md").exists()

    def test_version_file_increments(self, review_loop_repo: Path):
        """Subsequent version_file calls increment version number."""
        from agenttree.issues import create_issue

        agenttree_path = review_loop_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=review_loop_repo / ".agenttree.yaml"):
                issue = create_issue(title="Test Version Increment")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                # Create v1 manually
                (issue_dir / "independent_review_v1.md").write_text("First review")
                # Create new file to be versioned
                create_rejected_review(issue_dir)

                config = load_config()
                stage_config = config.get_stage("address_independent_review")

                errors = execute_hooks(issue_dir, "address_independent_review", stage_config, "post_start")
                assert errors == []

                # Should now have v2
                assert (issue_dir / "independent_review_v1.md").exists()
                assert (issue_dir / "independent_review_v2.md").exists()
                assert not (issue_dir / "independent_review.md").exists()


class TestLoopCheckHook:
    """Test the loop_check hook enforces iteration limits."""

    def test_loop_check_passes_under_limit(self, review_loop_repo: Path):
        """loop_check passes when under max iterations."""
        from agenttree.issues import create_issue

        agenttree_path = review_loop_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=review_loop_repo / ".agenttree.yaml"):
                issue = create_issue(title="Test Loop Under Limit")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                # Create 2 versioned files (under limit of 3)
                (issue_dir / "independent_review_v1.md").write_text("Review 1")
                (issue_dir / "independent_review_v2.md").write_text("Review 2")
                create_review_response(issue_dir)

                config = load_config()
                stage_config = config.get_stage("address_independent_review")

                errors = execute_hooks(issue_dir, "address_independent_review", stage_config, "pre_completion")
                assert errors == []

    def test_loop_check_fails_at_limit(self, review_loop_repo: Path):
        """loop_check fails when at max iterations."""
        from agenttree.issues import create_issue

        agenttree_path = review_loop_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=review_loop_repo / ".agenttree.yaml"):
                issue = create_issue(title="Test Loop At Limit")
                issue_dir = agenttree_path / "issues" / f"{issue.id}-{issue.slug}"

                # Create 3 versioned files (at limit)
                (issue_dir / "independent_review_v1.md").write_text("Review 1")
                (issue_dir / "independent_review_v2.md").write_text("Review 2")
                (issue_dir / "independent_review_v3.md").write_text("Review 3")
                create_review_response(issue_dir)

                config = load_config()
                stage_config = config.get_stage("address_independent_review")

                errors = execute_hooks(issue_dir, "address_independent_review", stage_config, "pre_completion")
                assert len(errors) > 0
                assert any("exceeded" in e.lower() or "iterations" in e.lower() for e in errors)


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
        """Test: reject → version → address → (would rollback) → re-review."""
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
                assert exc_info.value.target == "address_independent_review"

                # Step 3: Enter address_independent_review - version files
                stage_config = config.get_stage("address_independent_review")
                errors = execute_hooks(issue_dir, "address_independent_review", stage_config, "post_start")
                assert errors == []
                assert (issue_dir / "independent_review_v1.md").exists()

                # Step 4: Implementer addresses feedback
                create_review_response(issue_dir)

                # Step 5: Pre-completion should pass (under loop limit)
                errors = execute_hooks(issue_dir, "address_independent_review", stage_config, "pre_completion")
                assert errors == []

                # Step 6: After rollback, create new approved review
                create_approved_review(issue_dir)

                # Step 7: Now independent_code_review should pass
                stage_config = config.get_stage("independent_code_review")
                errors = execute_hooks(issue_dir, "independent_code_review", stage_config, "pre_completion")
                assert errors == []
