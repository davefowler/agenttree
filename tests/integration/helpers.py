"""Helper functions for integration tests.

Provides utilities to create valid content at each stage of the workflow,
advance issues through stages, and set up test scenarios.
"""

import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml


def create_valid_problem_md(issue_dir: Path) -> None:
    """Create a problem.md that passes all define hooks.

    Requires:
    - Context section not empty
    - Possible Solutions has list items
    """
    content = """# Problem Statement

Fix the login flow to handle edge cases properly.

## Context

The current login system has several issues:
- Users are not redirected properly after login
- Session tokens expire too quickly
- Error messages are not user-friendly

This affects approximately 15% of login attempts.

## Possible Solutions

- Add proper redirect handling in the auth middleware
- Implement token refresh mechanism
- Create user-friendly error messages with actionable guidance
- Add comprehensive logging for debugging

## Acceptance Criteria

- All login attempts redirect correctly
- Tokens refresh automatically before expiration
- Error messages are clear and helpful
"""
    (issue_dir / "problem.md").write_text(content)


def create_valid_research_md(issue_dir: Path) -> None:
    """Create a research.md that passes all research hooks.

    Requires:
    - Relevant Files section not empty
    - Existing Patterns section not empty
    """
    content = """# Research Notes

## Relevant Files

- `src/auth/login.py` - Main login handler
- `src/auth/session.py` - Session management
- `src/middleware/auth.py` - Auth middleware
- `src/utils/tokens.py` - Token utilities
- `tests/test_auth.py` - Existing auth tests

## Existing Patterns

The codebase uses a middleware-based authentication pattern:

1. **Session Management**: Sessions are stored in Redis with a 24-hour TTL
2. **Token Format**: JWT tokens with user_id and expiration claims
3. **Error Handling**: Errors are raised as HTTPExceptions with status codes

## Dependencies & Constraints

- Redis 6.0+ required for session storage
- JWT library: PyJWT 2.x
- Must maintain backwards compatibility with existing API

## Key Findings

1. The redirect URL is not preserved across the OAuth flow
2. Token refresh is implemented but not triggered automatically
3. Error messages use generic templates without context
"""
    (issue_dir / "research.md").write_text(content)


def create_valid_spec_md(issue_dir: Path) -> None:
    """Create a spec.md that passes all plan hooks.

    Requires:
    - Approach section not empty
    - Files to Modify has list items
    - Implementation Steps has list items
    - Test Plan section not empty
    """
    content = """# Implementation Specification

## Approach

We will fix the login flow by:
1. Storing the redirect URL in the session before OAuth redirect
2. Adding automatic token refresh 5 minutes before expiration
3. Creating context-aware error messages

This approach minimizes changes while addressing all three issues.

## Files to Modify

- `src/auth/login.py` - Add redirect URL storage
- `src/auth/session.py` - Implement token refresh logic
- `src/middleware/auth.py` - Add auto-refresh trigger
- `src/utils/errors.py` - Create error message templates

## Implementation Steps

- Add `redirect_url` field to session model
- Store redirect URL before OAuth flow starts
- Retrieve and use redirect URL after successful auth
- Implement `refresh_token_if_needed()` function
- Add refresh check to auth middleware
- Create error message templates with context placeholders
- Update existing error raises to use new templates

## Test Plan

- Unit tests for redirect URL storage and retrieval
- Unit tests for token refresh logic
- Integration tests for full login flow with redirect
- Manual testing of error messages in different scenarios

## Risks & Mitigations

- **Risk**: Token refresh could fail silently
- **Mitigation**: Add logging and fallback to re-authentication
"""
    (issue_dir / "spec.md").write_text(content)


def create_valid_spec_review_md(issue_dir: Path) -> None:
    """Create a spec_review.md that passes plan.assess hooks.

    Requires:
    - Assessment Summary section not empty
    """
    content = """# Specification Review

## Assessment Summary

The specification is well-structured and addresses all three issues identified in the problem statement. The approach is incremental and low-risk.

**Strengths:**
- Clear mapping between problems and solutions
- Minimal changes to existing code
- Comprehensive test plan

**Areas for Improvement:**
- Could add more detail on error message templates
- Consider adding metrics for success measurement

## Does This Solve the Problem?

Yes, the specification addresses all acceptance criteria:
- Redirect handling: Covered in steps 1-3
- Token refresh: Covered in steps 4-5
- Error messages: Covered in steps 6-7

## Confidence Level

High - The approach is straightforward and well-understood.

## Verdict

Ready for implementation.
"""
    (issue_dir / "spec_review.md").write_text(content)


def create_valid_review_md(issue_dir: Path, average: float = 8.0) -> None:
    """Create a review.md that passes all implement hooks.

    Requires:
    - Self-Review Checklist all checked (matches the items from implement-code_review.md)
    - average field >= 7
    - Critical Issues section empty

    NOTE: The checklist items below MUST match the items in _agenttree/templates/review.md.
    If the template changes, update these items to match.
    """
    content = f"""# Code Review

```yaml
scores:
  correctness: {average}
  completeness: {average}
  code_quality: {average}
  test_coverage: {average}
  average: {average}
```

## Overview

Implementation of the login flow fixes as specified. All three issues have been addressed:
1. Redirect URL is now preserved across OAuth flow
2. Token refresh happens automatically before expiration
3. Error messages include helpful context

## Changes Made

- Added `redirect_url` to session model
- Implemented `refresh_token_if_needed()` in session.py
- Updated auth middleware to trigger refresh
- Created error templates with context placeholders

## Self-Review Checklist

- [x] All tests pass locally
- [x] Code follows project coding standards and conventions
- [x] No security vulnerabilities (input validation, authentication, authorization)
- [x] Performance is acceptable (no obvious bottlenecks)
- [x] Documentation updated (README, API docs, comments where needed)
- [x] No TODO/FIXME comments left unresolved in production code
- [x] Reviewed the full diff line-by-line
- [x] PR description clearly explains the changes and why
- [x] Commit messages are clear and follow project conventions
- [x] No debug code, console.logs, or commented-out code left behind
- [x] All Critical Issues section above is empty
- [x] **Issue fully implemented** - All requirements from problem.md are addressed
- [x] **Code is wired up** - Not just staged; routes registered, handlers connected, feature accessible
- [x] **No cowardly code** - No silent exception swallowing, no graceful fallbacks that hide real errors, no tests that catch exceptions to pass silently, no empty except blocks
- [x] **No backward compatibility shims** - This is pre-launch. Remove old code, don't keep it "for compatibility"
- [x] **No deferred work** - Don't push cleanup to "follow-up issues". If you can do it now, do it now

## Critical Issues

<!-- None - all critical issues have been addressed -->

## High Priority Issues

<!-- None -->

## Medium Priority Issues

- Consider adding more comprehensive logging

## Suggestions

- Could add metrics dashboard for monitoring login success rate
"""
    (issue_dir / "review.md").write_text(content)


def create_failing_review_md(issue_dir: Path, reason: str = "low_score") -> None:
    """Create a review.md that will FAIL validation.

    Args:
        issue_dir: Path to issue directory
        reason: Why it should fail - "low_score", "unchecked", or "critical_issues"
    """
    if reason == "low_score":
        content = """# Code Review

```yaml
scores:
  correctness: 5
  completeness: 5
  average: 5
```

## Overview

Partial implementation.

## Self-Review Checklist

- [x] Code compiles
- [x] Tests pass

## Critical Issues

<!-- None -->
"""
    elif reason == "unchecked":
        content = """# Code Review

```yaml
scores:
  average: 8
```

## Overview

Implementation complete.

## Self-Review Checklist

- [x] Code compiles
- [ ] Tests pass
- [ ] No obvious bugs

## Critical Issues

<!-- None -->
"""
    elif reason == "critical_issues":
        content = """# Code Review

```yaml
scores:
  average: 8
```

## Overview

Implementation complete.

## Self-Review Checklist

- [x] Code compiles
- [x] Tests pass

## Critical Issues

- Security vulnerability in token handling
- Missing input validation
"""
    else:
        raise ValueError(f"Unknown failure reason: {reason}")

    (issue_dir / "review.md").write_text(content)


def make_commit(repo_path: Path, message: str = "Test commit") -> str:
    """Create a commit in the repository.

    Returns the commit hash.
    """
    # Create or modify a file
    test_file = repo_path / "test_change.txt"
    existing = test_file.read_text() if test_file.exists() else ""
    test_file.write_text(existing + f"\n{message}\n")

    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_path, check=True, capture_output=True
    )

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def get_current_branch(repo_path: Path) -> str:
    """Get the current branch name."""
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_path, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def create_branch(repo_path: Path, branch_name: str) -> None:
    """Create and checkout a new branch."""
    subprocess.run(
        ["git", "checkout", "-b", branch_name],
        cwd=repo_path, check=True, capture_output=True
    )


def has_uncommitted_changes(repo_path: Path) -> bool:
    """Check if there are uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path, check=True, capture_output=True, text=True
    )
    return bool(result.stdout.strip())


def get_unpushed_commits(repo_path: Path, branch: str = "HEAD") -> list[str]:
    """Get list of commits not pushed to origin.

    Returns empty list if no remote or no unpushed commits.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"origin/{branch}..{branch}", "--oneline"],
            cwd=repo_path, capture_output=True, text=True
        )
        if result.returncode != 0:
            return []
        return [line for line in result.stdout.strip().split("\n") if line]
    except Exception:
        return []


def setup_issue_at_stage(
    issue_dir: Path,
    stage: str,
    create_content: bool = True
) -> None:
    """Set up an issue at a specific stage with valid content.

    Creates all necessary files for the issue to be at the given stage.

    Args:
        issue_dir: Path to issue directory
        stage: Dot path (e.g., "explore.define", "implement.code")
        create_content: Whether to create content files
    """
    # Update issue.yaml
    yaml_path = issue_dir / "issue.yaml"
    with open(yaml_path) as f:
        data = yaml.safe_load(f)

    data["stage"] = stage
    # Remove substage if present (old format)
    data.pop("substage", None)

    with open(yaml_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)

    if not create_content:
        return

    # Create content files based on stage
    # Map dot paths to content creators
    stages_needing_content: dict[str, list] = {
        "explore.define": [create_valid_problem_md],
        "explore.research": [create_valid_problem_md, create_valid_research_md],
        "plan.draft": [create_valid_problem_md, create_valid_research_md, create_valid_spec_md],
        "plan.assess": [create_valid_problem_md, create_valid_research_md, create_valid_spec_md, create_valid_spec_review_md],
        "plan.revise": [create_valid_problem_md, create_valid_research_md, create_valid_spec_md, create_valid_spec_review_md],
        "plan.review": [create_valid_problem_md, create_valid_research_md, create_valid_spec_md, create_valid_spec_review_md],
        "implement.code": [create_valid_problem_md, create_valid_research_md, create_valid_spec_md, create_valid_spec_review_md],
        "implement.review": [create_valid_problem_md, create_valid_research_md, create_valid_spec_md, create_valid_spec_review_md, create_valid_review_md],
        "accepted": [create_valid_problem_md, create_valid_research_md, create_valid_spec_md, create_valid_spec_review_md, create_valid_review_md],
    }

    creators = stages_needing_content.get(stage, [])
    for creator in creators:
        creator(issue_dir)


def advance_to_stage(
    issue_id: str,
    target_stage: str,
    repo_path: Path | None = None,
    mock_hooks: bool = True
) -> None:
    """Advance an issue to a specific stage, creating valid content along the way.

    This is a helper for tests that need an issue at a specific stage
    without testing all the intermediate transitions.

    Args:
        issue_id: Issue ID
        target_stage: Target dot path (e.g., "implement.code")
        repo_path: Optional path to repo for commit creation
        mock_hooks: Whether to mock hooks for speed
    """
    from agenttree.issues import get_issue_dir, update_issue_stage

    issue_dir = get_issue_dir(issue_id)
    if not issue_dir:
        raise ValueError(f"Issue {issue_id} not found")

    # Create all necessary content
    setup_issue_at_stage(issue_dir, target_stage, create_content=True)

    # If we need commits for feedback stage
    if target_stage == "implement.feedback":
        if repo_path:
            make_commit(repo_path, f"Implementation for {issue_id}")

    # Update the stage directly (bypassing hooks for speed)
    if mock_hooks:
        with patch("agenttree.issues.sync_agents_repo", return_value=True):
            update_issue_stage(issue_id, target_stage)
    else:
        update_issue_stage(issue_id, target_stage)
