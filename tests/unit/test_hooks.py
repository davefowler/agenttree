"""Tests for agenttree.hooks module."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call

import pytest

from agenttree.issues import Issue, Stage, Priority


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


class TestHookRegistry:
    """Tests for HookRegistry class."""

    def test_registry_initialization(self):
        """HookRegistry should initialize with empty hook dictionaries."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        assert isinstance(registry.pre_transition, dict)
        assert isinstance(registry.post_transition, dict)
        assert isinstance(registry.on_enter, dict)
        assert isinstance(registry.on_exit, dict)
        assert len(registry.pre_transition) == 0
        assert len(registry.post_transition) == 0
        assert len(registry.on_enter) == 0
        assert len(registry.on_exit) == 0

    def test_register_pre_transition_hook(self):
        """Should register a pre-transition hook."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        def my_hook(issue):
            pass

        registry.register_pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, my_hook)

        key = (Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        assert key in registry.pre_transition
        assert my_hook in registry.pre_transition[key]

    def test_register_multiple_pre_transition_hooks(self):
        """Should register multiple hooks for the same transition."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        def hook1(issue):
            pass

        def hook2(issue):
            pass

        registry.register_pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, hook1)
        registry.register_pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, hook2)

        key = (Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        assert len(registry.pre_transition[key]) == 2
        assert hook1 in registry.pre_transition[key]
        assert hook2 in registry.pre_transition[key]

    def test_register_post_transition_hook(self):
        """Should register a post-transition hook."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        def my_hook(issue):
            pass

        registry.register_post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, my_hook)

        key = (Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        assert key in registry.post_transition
        assert my_hook in registry.post_transition[key]

    def test_register_on_enter_hook(self):
        """Should register an on-enter hook."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        def my_hook(issue):
            pass

        registry.register_on_enter(Stage.RESEARCH, my_hook)

        assert Stage.RESEARCH in registry.on_enter
        assert my_hook in registry.on_enter[Stage.RESEARCH]

    def test_register_on_exit_hook(self):
        """Should register an on-exit hook."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        def my_hook(issue):
            pass

        registry.register_on_exit(Stage.IMPLEMENT, my_hook)

        assert Stage.IMPLEMENT in registry.on_exit
        assert my_hook in registry.on_exit[Stage.IMPLEMENT]

    def test_execute_pre_transition_success(self):
        """Should execute pre-transition hooks successfully."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        executed = []

        def hook1(issue):
            executed.append("hook1")

        def hook2(issue):
            executed.append("hook2")

        registry.register_pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, hook1)
        registry.register_pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, hook2)

        issue = Mock(spec=Issue)
        registry.execute_pre_transition(issue, Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)

        assert executed == ["hook1", "hook2"]

    def test_execute_pre_transition_validation_error(self):
        """Should raise ValidationError if a pre-hook fails."""
        from agenttree.hooks import HookRegistry, ValidationError

        registry = HookRegistry()

        def failing_hook(issue):
            raise ValidationError("Validation failed")

        registry.register_pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, failing_hook)

        issue = Mock(spec=Issue)

        with pytest.raises(ValidationError, match="Validation failed"):
            registry.execute_pre_transition(issue, Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)

    def test_execute_pre_transition_no_hooks(self):
        """Should handle case where no hooks are registered."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()
        issue = Mock(spec=Issue)

        # Should not raise any errors
        registry.execute_pre_transition(issue, Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)

    def test_execute_post_transition_success(self):
        """Should execute post-transition hooks successfully."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        executed = []

        def hook1(issue):
            executed.append("hook1")

        def hook2(issue):
            executed.append("hook2")

        registry.register_post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, hook1)
        registry.register_post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, hook2)

        issue = Mock(spec=Issue)
        registry.execute_post_transition(issue, Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)

        assert executed == ["hook1", "hook2"]

    def test_execute_post_transition_logs_errors_but_continues(self):
        """Should log errors in post-hooks but not raise."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        executed = []

        def failing_hook(issue):
            executed.append("failing_hook")
            raise Exception("Post-hook error")

        def success_hook(issue):
            executed.append("success_hook")

        registry.register_post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, failing_hook)
        registry.register_post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, success_hook)

        issue = Mock(spec=Issue)

        # Should not raise, but should execute both hooks
        registry.execute_post_transition(issue, Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)

        assert "failing_hook" in executed
        assert "success_hook" in executed

    def test_execute_on_enter_success(self):
        """Should execute on-enter hooks successfully."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        executed = []

        def hook1(issue):
            executed.append("hook1")

        registry.register_on_enter(Stage.RESEARCH, hook1)

        issue = Mock(spec=Issue)
        registry.execute_on_enter(issue, Stage.RESEARCH)

        assert executed == ["hook1"]

    def test_execute_on_exit_success(self):
        """Should execute on-exit hooks successfully."""
        from agenttree.hooks import HookRegistry

        registry = HookRegistry()

        executed = []

        def hook1(issue):
            executed.append("hook1")

        registry.register_on_exit(Stage.IMPLEMENT, hook1)

        issue = Mock(spec=Issue)
        registry.execute_on_exit(issue, Stage.IMPLEMENT)

        assert executed == ["hook1"]


class TestHelperFunctions:
    """Tests for helper functions get_registry and execute_transition_hooks."""

    def test_get_registry_returns_global_registry(self):
        """Should return the global HookRegistry instance."""
        from agenttree.hooks import get_registry, _registry

        result = get_registry()
        assert result is _registry

    def test_get_registry_returns_hookregistry_instance(self):
        """Should return a HookRegistry instance."""
        from agenttree.hooks import get_registry, HookRegistry

        result = get_registry()
        assert isinstance(result, HookRegistry)

    def test_execute_transition_hooks_calls_hooks_in_order(self):
        """Should execute hooks in correct order: on_exit, pre, post, on_enter."""
        from agenttree.hooks import execute_transition_hooks, HookRegistry

        # Create a fresh registry for this test
        registry = HookRegistry()
        execution_order = []

        def on_exit_hook(issue):
            execution_order.append("on_exit")

        def pre_hook(issue):
            execution_order.append("pre")

        def post_hook(issue):
            execution_order.append("post")

        def on_enter_hook(issue):
            execution_order.append("on_enter")

        registry.register_on_exit(Stage.IMPLEMENT, on_exit_hook)
        registry.register_pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, pre_hook)
        registry.register_post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, post_hook)
        registry.register_on_enter(Stage.IMPLEMENTATION_REVIEW, on_enter_hook)

        # Patch the global registry
        import agenttree.hooks
        original_registry = agenttree.hooks._registry
        agenttree.hooks._registry = registry

        try:
            mock_issue = Mock(spec=Issue)
            execute_transition_hooks(mock_issue, Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)

            assert execution_order == ["on_exit", "pre", "post", "on_enter"]
        finally:
            agenttree.hooks._registry = original_registry

    def test_execute_transition_hooks_raises_on_pre_validation_error(self):
        """Should raise ValidationError if pre-transition hook fails."""
        from agenttree.hooks import execute_transition_hooks, HookRegistry, ValidationError

        registry = HookRegistry()

        def failing_pre_hook(issue):
            raise ValidationError("Blocked!")

        registry.register_pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW, failing_pre_hook)

        import agenttree.hooks
        original_registry = agenttree.hooks._registry
        agenttree.hooks._registry = registry

        try:
            mock_issue = Mock(spec=Issue)
            with pytest.raises(ValidationError, match="Blocked!"):
                execute_transition_hooks(mock_issue, Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        finally:
            agenttree.hooks._registry = original_registry


class TestHookDecorators:
    """Tests for hook decorator functions."""

    def test_pre_transition_decorator(self):
        """Should register hook via decorator."""
        from agenttree.hooks import pre_transition, _registry

        # Clear registry for this test
        _registry.pre_transition.clear()

        @pre_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        def my_hook(issue):
            pass

        key = (Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        assert key in _registry.pre_transition
        assert my_hook in _registry.pre_transition[key]

    def test_post_transition_decorator(self):
        """Should register hook via decorator."""
        from agenttree.hooks import post_transition, _registry

        # Clear registry for this test
        _registry.post_transition.clear()

        @post_transition(Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        def my_hook(issue):
            pass

        key = (Stage.IMPLEMENT, Stage.IMPLEMENTATION_REVIEW)
        assert key in _registry.post_transition
        assert my_hook in _registry.post_transition[key]

    def test_on_enter_decorator(self):
        """Should register hook via decorator."""
        from agenttree.hooks import on_enter, _registry

        # Clear registry for this test
        _registry.on_enter.clear()

        @on_enter(Stage.RESEARCH)
        def my_hook(issue):
            pass

        assert Stage.RESEARCH in _registry.on_enter
        assert my_hook in _registry.on_enter[Stage.RESEARCH]

    def test_on_exit_decorator(self):
        """Should register hook via decorator."""
        from agenttree.hooks import on_exit, _registry

        # Clear registry for this test
        _registry.on_exit.clear()

        @on_exit(Stage.IMPLEMENT)
        def my_hook(issue):
            pass

        assert Stage.IMPLEMENT in _registry.on_exit
        assert my_hook in _registry.on_exit[Stage.IMPLEMENT]


@pytest.fixture
def mock_issue():
    """Create a mock Issue object."""
    return Issue(
        id="023",
        slug="test-issue",
        title="Test Issue",
        created="2026-01-11T12:00:00Z",
        updated="2026-01-11T12:00:00Z",
        stage=Stage.IMPLEMENT,
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

        result = auto_commit_changes(Mock(), Stage.IMPLEMENT)

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
            stage=Stage.IMPLEMENT,
        )

        result = auto_commit_changes(issue, Stage.IMPLEMENT)

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

        msg = generate_commit_message(mock_issue, Stage.IMPLEMENT)

        assert "Implement" in msg
        assert "#023" in msg
        assert "Test Issue" in msg


class TestValidationHooks:
    """Tests for pre-transition validation hooks."""

    @patch('agenttree.hooks.has_commits_to_push')
    def test_require_commits_for_review_success(self, mock_has_commits, mock_issue):
        """Should pass when commits exist."""
        from agenttree.hooks import require_commits_for_review

        mock_has_commits.return_value = True

        # Should not raise
        require_commits_for_review(mock_issue)

    @patch('agenttree.hooks.has_commits_to_push')
    def test_require_commits_for_review_fails_no_commits(self, mock_has_commits, mock_issue):
        """Should block transition when no commits to push."""
        from agenttree.hooks import require_commits_for_review, ValidationError

        mock_has_commits.return_value = False

        with pytest.raises(ValidationError, match="No commits to push"):
            require_commits_for_review(mock_issue)

    @patch('agenttree.github.is_pr_approved')
    def test_require_pr_approval_success(self, mock_is_approved, mock_issue):
        """Should pass when PR is approved."""
        from agenttree.hooks import require_pr_approval

        mock_is_approved.return_value = True
        mock_issue.pr_number = 123

        # Should not raise
        require_pr_approval(mock_issue)

    @patch('agenttree.github.is_pr_approved')
    def test_require_pr_approval_fails_not_approved(self, mock_is_approved, mock_issue):
        """Should block transition when PR not approved."""
        from agenttree.hooks import require_pr_approval, ValidationError

        mock_is_approved.return_value = False
        mock_issue.pr_number = 123

        with pytest.raises(ValidationError, match="requires approval"):
            require_pr_approval(mock_issue)

    def test_require_pr_approval_fails_no_pr_number(self, mock_issue):
        """Should block transition when no PR number found."""
        from agenttree.hooks import require_pr_approval, ValidationError

        mock_issue.pr_number = None

        with pytest.raises(ValidationError, match="No PR number found"):
            require_pr_approval(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_review_md_for_pr_success(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should pass when review.md exists with empty Critical Issues section."""
        from agenttree.hooks import require_review_md_for_pr

        # Setup: Create review.md with empty Critical Issues section
        mock_get_issue_dir.return_value = tmp_path
        review_content = """# Code Review - Issue #023

## Critical Issues (Blocking)

<!-- MUST be empty before creating PR -->

---

## Suggestions

- Consider adding more tests
"""
        (tmp_path / "review.md").write_text(review_content)

        # Should not raise
        require_review_md_for_pr(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_review_md_for_pr_fails_missing_file(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should block transition when review.md doesn't exist."""
        from agenttree.hooks import require_review_md_for_pr, ValidationError

        mock_get_issue_dir.return_value = tmp_path
        # Don't create review.md

        with pytest.raises(ValidationError, match="review.md not found"):
            require_review_md_for_pr(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_review_md_for_pr_fails_unchecked_items(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should block transition when Critical Issues has unchecked items."""
        from agenttree.hooks import require_review_md_for_pr, ValidationError

        mock_get_issue_dir.return_value = tmp_path
        review_content = """# Code Review - Issue #023

## Critical Issues (Blocking)

- [ ] Security: SQL injection vulnerability in user input

---

## Suggestions
"""
        (tmp_path / "review.md").write_text(review_content)

        with pytest.raises(ValidationError, match="Critical Issues"):
            require_review_md_for_pr(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_review_md_for_pr_fails_checked_items(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should block transition when Critical Issues has checked items (should be removed, not checked)."""
        from agenttree.hooks import require_review_md_for_pr, ValidationError

        mock_get_issue_dir.return_value = tmp_path
        review_content = """# Code Review - Issue #023

## Critical Issues (Blocking)

- [x] Security: Fixed SQL injection vulnerability

---

## Suggestions
"""
        (tmp_path / "review.md").write_text(review_content)

        with pytest.raises(ValidationError, match="Critical Issues"):
            require_review_md_for_pr(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_review_md_for_pr_success_only_comments(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should pass when Critical Issues section only has HTML comments."""
        from agenttree.hooks import require_review_md_for_pr

        mock_get_issue_dir.return_value = tmp_path
        review_content = """# Code Review - Issue #023

## Critical Issues (Blocking)

<!-- MUST be empty before creating PR -->
<!-- Format: - [ ] Description of critical bug/security issue -->

---

## High Priority Issues
"""
        (tmp_path / "review.md").write_text(review_content)

        # Should not raise
        require_review_md_for_pr(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_spec_md_for_implement_success(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should pass when spec.md (or plan.md) exists with meaningful Approach content."""
        from agenttree.hooks import require_spec_md_for_implement

        mock_get_issue_dir.return_value = tmp_path
        plan_content = """# Implementation Plan

## Problem Summary

Brief summary of the problem.

## Approach

This is a meaningful approach description that explains the implementation strategy
with more than 20 characters of content to pass validation.

## Files to Modify

- file1.py
- file2.py
"""
        (tmp_path / "plan.md").write_text(plan_content)

        # Should not raise (plan.md is accepted as legacy name)
        require_spec_md_for_implement(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_spec_md_for_implement_fails_missing_file(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should block transition when spec.md doesn't exist."""
        from agenttree.hooks import require_spec_md_for_implement, ValidationError

        mock_get_issue_dir.return_value = tmp_path
        # Don't create spec.md or plan.md

        with pytest.raises(ValidationError, match="spec.md not found"):
            require_spec_md_for_implement(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_spec_md_for_implement_fails_empty_approach(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should block transition when Approach section is empty."""
        from agenttree.hooks import require_spec_md_for_implement, ValidationError

        mock_get_issue_dir.return_value = tmp_path
        plan_content = """# Implementation Plan

## Problem Summary

Brief summary.

## Approach

<!-- Describe your approach here -->

## Files to Modify

- file1.py
"""
        (tmp_path / "plan.md").write_text(plan_content)

        with pytest.raises(ValidationError, match="Approach section is too short"):
            require_spec_md_for_implement(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_spec_md_for_implement_fails_short_approach(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should block transition when Approach section has less than 20 chars."""
        from agenttree.hooks import require_spec_md_for_implement, ValidationError

        mock_get_issue_dir.return_value = tmp_path
        plan_content = """# Implementation Plan

## Approach

Short.

## Files to Modify
"""
        (tmp_path / "plan.md").write_text(plan_content)

        with pytest.raises(ValidationError, match="Approach section is too short"):
            require_spec_md_for_implement(mock_issue)

    @patch('agenttree.hooks._get_issue_dir')
    def test_require_spec_md_for_implement_ignores_html_comments(self, mock_get_issue_dir, mock_issue, tmp_path):
        """Should ignore HTML comments when counting Approach content length."""
        from agenttree.hooks import require_spec_md_for_implement, ValidationError

        mock_get_issue_dir.return_value = tmp_path
        plan_content = """# Implementation Plan

## Approach

<!-- This is a very long HTML comment that should be ignored when counting -->
<!-- Another comment here -->
Too short

## Files to Modify
"""
        (tmp_path / "plan.md").write_text(plan_content)

        with pytest.raises(ValidationError, match="Approach section is too short"):
            require_spec_md_for_implement(mock_issue)


class TestMissingHooks:
    """Document validation hooks that are mentioned but not implemented.

    This test class serves as documentation for expected hooks that don't
    exist in the codebase yet. These should be implemented in future issues.
    """

    def test_require_problem_md_for_research_not_implemented(self):
        """Document that require_problem_md_for_research hook doesn't exist.

        Expected behavior: Should block PROBLEM_REVIEW -> RESEARCH transition
        when problem.md is missing or empty.

        This hook is mentioned in issue #038 problem.md but was never implemented.
        """
        from agenttree.hooks import _registry, Stage

        # Check if this hook is registered for the expected transition
        key = (Stage.PROBLEM_REVIEW, Stage.RESEARCH)
        hooks_for_transition = _registry.pre_transition.get(key, [])

        # Get hook names
        hook_names = [hook.__name__ for hook in hooks_for_transition]

        # Document the gap - this assertion will PASS because the hook doesn't exist
        # When the hook is implemented, update this test to verify it works
        assert "require_problem_md_for_research" not in hook_names, (
            "Hook require_problem_md_for_research has been implemented! "
            "Update this test to verify its behavior instead of documenting its absence."
        )


class TestActionHooks:
    """Tests for post-transition action hooks."""

    @patch('agenttree.hooks.get_current_branch')
    @patch('agenttree.hooks.push_branch_to_remote')
    @patch('agenttree.github.create_pr')
    @patch('agenttree.issues.update_issue_metadata')
    def test_create_pull_request_success(
        self, mock_update_metadata, mock_create_pr, mock_push, mock_get_branch, mock_issue
    ):
        """Should create PR successfully."""
        from agenttree.hooks import create_pull_request_hook
        from agenttree.github import PullRequest

        mock_get_branch.return_value = "agenttree-agent-1-work"
        mock_create_pr.return_value = PullRequest(
            number=123,
            url="https://github.com/owner/repo/pull/123",
            title="Test PR",
            branch="agenttree-agent-1-work"
        )

        create_pull_request_hook(mock_issue)

        # Should push branch
        mock_push.assert_called_once_with("agenttree-agent-1-work")

        # Should create PR with correct parameters
        mock_create_pr.assert_called_once()
        call_args = mock_create_pr.call_args
        assert "[Issue 023]" in call_args.kwargs['title']
        assert "Test Issue" in call_args.kwargs['title']
        assert "Issue #023" in call_args.kwargs['body']
        assert call_args.kwargs['branch'] == "agenttree-agent-1-work"
        assert call_args.kwargs['base'] == "main"

        # Should update issue metadata twice:
        # 1. First call with just branch
        # 2. Second call with PR info
        assert mock_update_metadata.call_count == 2
        # Verify the final call has PR info
        mock_update_metadata.assert_called_with(
            "023",
            pr_number=123,
            pr_url="https://github.com/owner/repo/pull/123",
            branch="agenttree-agent-1-work"
        )

    @patch('agenttree.hooks.get_current_branch')
    @patch('agenttree.hooks.push_branch_to_remote')
    @patch('agenttree.github.create_pr')
    def test_create_pull_request_handles_push_failure(
        self, mock_create_pr, mock_push, mock_get_branch, mock_issue
    ):
        """Should handle push failure gracefully."""
        from agenttree.hooks import create_pull_request_hook

        mock_get_branch.return_value = "agenttree-agent-1-work"
        mock_push.side_effect = subprocess.CalledProcessError(1, 'git push')

        # Should raise the error (post-hooks log but still raise for retry)
        with pytest.raises(subprocess.CalledProcessError):
            create_pull_request_hook(mock_issue)

        # Should not create PR if push fails
        mock_create_pr.assert_not_called()

    @patch('agenttree.github.merge_pr')
    def test_merge_pull_request_success(self, mock_merge_pr, mock_issue):
        """Should merge PR successfully."""
        from agenttree.hooks import merge_pull_request_hook

        mock_issue.pr_number = 123

        merge_pull_request_hook(mock_issue)

        # Should merge PR with squash method
        mock_merge_pr.assert_called_once_with(123, method="squash")

    def test_merge_pull_request_no_pr_number(self, mock_issue):
        """Should handle missing PR number gracefully."""
        from agenttree.hooks import merge_pull_request_hook

        mock_issue.pr_number = None

        # Should not raise, just log warning
        merge_pull_request_hook(mock_issue)
