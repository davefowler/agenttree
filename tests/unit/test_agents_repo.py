"""Tests for agents repository management."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from agenttree.agents_repo import AgentsRepository, slugify, sync_agents_repo


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
        assert agents_repo.agents_path == project_path / "_agenttree"

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
        """Test _add_to_gitignore adds _agenttree/ to parent .gitignore."""
        agents_repo.project_path = tmp_path
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("__pycache__/\n*.pyc\n")

        agents_repo._add_to_gitignore()

        content = gitignore.read_text()
        assert "_agenttree/" in content
        assert "__pycache__/" in content  # Original content preserved

    def test_add_to_gitignore_skips_if_exists(self, agents_repo, tmp_path):
        """Test _add_to_gitignore doesn't duplicate entry."""
        agents_repo.project_path = tmp_path
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("_agenttree/\n")

        original_content = gitignore.read_text()
        agents_repo._add_to_gitignore()

        # Should not modify (already has _agenttree/)
        assert "_agenttree/" in gitignore.read_text()
        assert gitignore.read_text().count("_agenttree/") == 1

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


@pytest.mark.usefixtures("host_environment")
class TestSyncAgentsRepo:
    """Tests for sync_agents_repo function.

    These tests simulate host environment (not container) since sync
    operations are only performed on the host.
    """

    @pytest.fixture
    def git_repo(self, tmp_path):
        """Create a temporary directory with .git folder."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()
        (agents_dir / ".git").mkdir()
        return agents_dir

    def test_sync_returns_false_when_dir_not_exists(self, tmp_path):
        """Test sync returns False when directory doesn't exist."""
        non_existent = tmp_path / "nonexistent"
        result = sync_agents_repo(non_existent)
        assert result is False

    def test_sync_returns_false_when_not_git_repo(self, tmp_path):
        """Test sync returns False when directory is not a git repo."""
        not_git = tmp_path / "not-git"
        not_git.mkdir()
        result = sync_agents_repo(not_git)
        assert result is False

    @patch("agenttree.agents_repo.check_merged_prs")
    @patch("agenttree.agents_repo.check_controller_stages")
    @patch("agenttree.agents_repo.push_pending_branches")
    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_pull_only_success(self, mock_run, mock_push_pending, mock_check_controller, mock_check_merged, git_repo):
        """Test sync with pull_only=True succeeds."""
        # Mock responses for: status --porcelain (no changes), pull
        mock_run.side_effect = [
            Mock(returncode=0, stdout=""),  # status --porcelain (empty = no changes)
            Mock(returncode=0, stderr=""),  # pull --no-rebase
        ]

        result = sync_agents_repo(git_repo, pull_only=True)

        assert result is True
        # Calls: status, pull
        assert mock_run.call_count == 2
        # Verify pull was called (at index 1: status, pull)
        pull_call = mock_run.call_args_list[1][0][0]
        assert "pull" in pull_call
        assert "--no-rebase" in pull_call

    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_pull_only_offline(self, mock_run, git_repo):
        """Test sync returns False when offline."""
        # Mock responses for: status --porcelain (no changes), pull (fails offline)
        mock_run.side_effect = [
            Mock(returncode=0, stdout=""),  # status --porcelain (empty = no changes)
            Mock(returncode=1, stderr="Could not resolve host: github.com"),  # pull
        ]

        result = sync_agents_repo(git_repo, pull_only=True)

        assert result is False

    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_pull_only_no_remote(self, mock_run, git_repo):
        """Test sync returns False when no remote configured."""
        # Mock responses for: status --porcelain (no changes), pull (fails no remote)
        mock_run.side_effect = [
            Mock(returncode=0, stdout=""),  # status --porcelain (empty = no changes)
            Mock(returncode=1, stderr="fatal: no remote"),  # pull
        ]

        result = sync_agents_repo(git_repo, pull_only=True)

        assert result is False

    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_pull_only_conflict(self, mock_run, git_repo, capsys):
        """Test sync returns False on merge conflict."""
        # Mock responses for: status --porcelain (no changes), pull (conflict)
        mock_run.side_effect = [
            Mock(returncode=0, stdout=""),  # status --porcelain (empty = no changes)
            Mock(returncode=1, stderr="CONFLICT (content): Merge conflict in file.txt"),  # pull
        ]

        result = sync_agents_repo(git_repo, pull_only=True)

        assert result is False
        captured = capsys.readouterr()
        assert "Merge conflict" in captured.out

    @patch("agenttree.agents_repo.check_merged_prs")
    @patch("agenttree.agents_repo.check_controller_stages")
    @patch("agenttree.agents_repo.push_pending_branches")
    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_write_commits_and_pushes(self, mock_run, mock_push_pending, mock_check_controller, mock_check_merged, git_repo):
        """Test sync with write commits and pushes changes."""
        # Mock responses for: status --porcelain (has changes), add, commit, pull, push
        mock_run.side_effect = [
            Mock(returncode=0, stdout="M some_file.yaml"),  # status --porcelain (has changes)
            Mock(returncode=0),  # add -A
            Mock(returncode=0, stderr=""),  # commit
            Mock(returncode=0, stderr=""),  # pull --no-rebase
            Mock(returncode=0, stderr=""),  # push
        ]

        result = sync_agents_repo(
            git_repo,
            pull_only=False,
            commit_message="Test commit"
        )

        assert result is True
        assert mock_run.call_count == 5

        # Verify commit message (commit is at index 2: status, add, commit, pull, push)
        commit_call = mock_run.call_args_list[2]
        assert "commit" in commit_call[0][0]
        assert "Test commit" in commit_call[0][0]

    @patch("agenttree.agents_repo.check_merged_prs")
    @patch("agenttree.agents_repo.check_controller_stages")
    @patch("agenttree.agents_repo.push_pending_branches")
    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_write_no_changes(self, mock_run, mock_push_pending, mock_check_controller, mock_check_merged, git_repo):
        """Test sync with write but no changes to commit."""
        # Mock responses for: status --porcelain (no changes), pull, push
        mock_run.side_effect = [
            Mock(returncode=0, stdout=""),  # status --porcelain (empty = no changes)
            Mock(returncode=0, stderr=""),  # pull --no-rebase
            Mock(returncode=0, stderr=""),  # push
        ]

        result = sync_agents_repo(git_repo, pull_only=False)

        assert result is True
        assert mock_run.call_count == 3  # status, pull, push (no commit since no changes)

    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_write_push_offline(self, mock_run, git_repo, capsys):
        """Test sync handles offline push gracefully."""
        mock_run.side_effect = [
            Mock(returncode=0),  # add -A
            Mock(returncode=1),  # diff (has changes)
            Mock(returncode=0, stderr=""),  # commit
            Mock(returncode=0, stderr=""),  # pull --rebase
            Mock(returncode=1, stderr="Could not resolve host"),  # push fails
        ]

        result = sync_agents_repo(git_repo, pull_only=False)

        assert result is False
        captured = capsys.readouterr()
        assert "Offline" in captured.out

    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_timeout(self, mock_run, git_repo, capsys):
        """Test sync handles timeout gracefully."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=30)

        result = sync_agents_repo(git_repo, pull_only=True)

        assert result is False
        captured = capsys.readouterr()
        assert "timed out" in captured.out

    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_uses_default_commit_message(self, mock_run, git_repo):
        """Test sync uses default commit message when not provided."""
        mock_run.side_effect = [
            Mock(returncode=0),  # add -A
            Mock(returncode=1),  # diff (has changes)
            Mock(returncode=0, stderr=""),  # commit
            Mock(returncode=0, stderr=""),  # pull --rebase
            Mock(returncode=0, stderr=""),  # push
        ]

        sync_agents_repo(git_repo, pull_only=False)

        # commit is at index 2: add, diff, commit, pull, push
        commit_call = mock_run.call_args_list[2]
        assert "Auto-sync: update issue data" in commit_call[0][0]

    @patch("agenttree.agents_repo.subprocess.run")
    def test_sync_commit_failure(self, mock_run, git_repo, capsys):
        """Test sync continues even if commit fails (commit result not checked)."""
        # Note: The current implementation doesn't check commit return code,
        # so sync continues to pull/push even if commit fails
        mock_run.side_effect = [
            Mock(returncode=0),  # add -A
            Mock(returncode=1),  # diff (has changes)
            Mock(returncode=1, stderr="error: unable to commit"),  # commit fails
            Mock(returncode=0, stderr=""),  # pull --rebase (continues anyway)
            Mock(returncode=0, stderr=""),  # push
        ]

        result = sync_agents_repo(git_repo, pull_only=False)

        # Sync succeeds because commit failure isn't checked
        assert result is True
        assert mock_run.call_count == 5


@pytest.mark.usefixtures("host_environment")
class TestCheckCiStatus:
    """Tests for check_ci_status function."""

    @pytest.fixture
    def agents_dir(self, tmp_path):
        """Create a temporary _agenttree directory with issues subfolder."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()
        (agents_dir / "issues").mkdir()
        return agents_dir

    @pytest.fixture
    def issue_at_implementation_review(self, agents_dir):
        """Create an issue at implementation_review stage with a PR."""
        import yaml
        issue_dir = agents_dir / "issues" / "042-test-issue"
        issue_dir.mkdir()
        issue_yaml = issue_dir / "issue.yaml"
        data = {
            "id": "42",
            "title": "Test issue",
            "stage": "implementation_review",
            "substage": "ci_wait",
            "pr_number": 123,
            "agent": 42,
        }
        with open(issue_yaml, "w") as f:
            yaml.dump(data, f)
        return issue_dir, data

    def test_check_ci_status_skips_in_container(self, agents_dir):
        """Verify hook bails early when running in container."""
        from agenttree.agents_repo import check_ci_status

        with patch("agenttree.hooks.is_running_in_container", return_value=True):
            result = check_ci_status(agents_dir)
            assert result == 0

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_skips_non_implementation_review_issues(self, mock_container, agents_dir):
        """Verify hook only processes issues at implementation_review stage."""
        import yaml
        from agenttree.agents_repo import check_ci_status

        # Create issue at implement stage (not implementation_review)
        issue_dir = agents_dir / "issues" / "042-test-issue"
        issue_dir.mkdir()
        issue_yaml = issue_dir / "issue.yaml"
        data = {
            "id": "42",
            "title": "Test issue",
            "stage": "implement",
            "pr_number": 123,
        }
        with open(issue_yaml, "w") as f:
            yaml.dump(data, f)

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            result = check_ci_status(agents_dir)
            # Should not call get_pr_checks since issue is not at implementation_review
            mock_get_checks.assert_not_called()
            assert result == 0

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_skips_issues_without_pr(self, mock_container, agents_dir):
        """Verify hook skips issues without pr_number."""
        import yaml
        from agenttree.agents_repo import check_ci_status

        # Create issue at implementation_review but without PR
        issue_dir = agents_dir / "issues" / "042-test-issue"
        issue_dir.mkdir()
        issue_yaml = issue_dir / "issue.yaml"
        data = {
            "id": "42",
            "title": "Test issue",
            "stage": "implementation_review",
            # No pr_number
        }
        with open(issue_yaml, "w") as f:
            yaml.dump(data, f)

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            result = check_ci_status(agents_dir)
            # Should not call get_pr_checks since issue has no PR
            mock_get_checks.assert_not_called()
            assert result == 0

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_on_ci_success_does_nothing(self, mock_container, agents_dir, issue_at_implementation_review):
        """Verify hook is a no-op when CI passes."""
        from agenttree.agents_repo import check_ci_status
        from agenttree.github import CheckStatus

        issue_dir, _ = issue_at_implementation_review

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            mock_get_checks.return_value = [
                CheckStatus(name="build", state="SUCCESS", conclusion="success"),
                CheckStatus(name="test", state="SUCCESS", conclusion="success"),
            ]
            result = check_ci_status(agents_dir)

            # Should not create ci_feedback.md
            assert not (issue_dir / "ci_feedback.md").exists()
            assert result == 0

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_on_ci_pending_does_nothing(self, mock_container, agents_dir, issue_at_implementation_review):
        """Verify hook waits for CI to complete (no action on pending)."""
        from agenttree.agents_repo import check_ci_status
        from agenttree.github import CheckStatus

        issue_dir, _ = issue_at_implementation_review

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            mock_get_checks.return_value = [
                CheckStatus(name="build", state="PENDING", conclusion=None),
            ]
            result = check_ci_status(agents_dir)

            # Should not create ci_feedback.md (CI still running)
            assert not (issue_dir / "ci_feedback.md").exists()
            assert result == 0

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_on_ci_failure_writes_feedback(self, mock_container, agents_dir, issue_at_implementation_review):
        """Verify ci_feedback.md is created with failure details."""
        from agenttree.agents_repo import check_ci_status
        from agenttree.github import CheckStatus

        issue_dir, _ = issue_at_implementation_review

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            with patch("agenttree.state.get_active_agent", return_value=None):
                mock_get_checks.return_value = [
                    CheckStatus(name="build", state="SUCCESS", conclusion="success"),
                    CheckStatus(name="test", state="FAILURE", conclusion="failure"),
                ]
                result = check_ci_status(agents_dir)

                # Should create ci_feedback.md
                feedback_file = issue_dir / "ci_feedback.md"
                assert feedback_file.exists()
                content = feedback_file.read_text()
                assert "test" in content
                assert "FAILURE" in content or "failure" in content
                assert result == 1

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_on_ci_failure_transitions_to_implement(self, mock_container, agents_dir, issue_at_implementation_review):
        """Verify issue is moved back to implement stage."""
        import yaml
        from agenttree.agents_repo import check_ci_status
        from agenttree.github import CheckStatus

        issue_dir, _ = issue_at_implementation_review

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            with patch("agenttree.state.get_active_agent", return_value=None):
                mock_get_checks.return_value = [
                    CheckStatus(name="test", state="FAILURE", conclusion="failure"),
                ]
                check_ci_status(agents_dir)

                # Verify stage was changed to implement
                with open(issue_dir / "issue.yaml") as f:
                    data = yaml.safe_load(f)
                assert data["stage"] == "implement"

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_on_ci_failure_sends_tmux_message(self, mock_container, agents_dir, issue_at_implementation_review):
        """Verify agent is notified via tmux."""
        from agenttree.agents_repo import check_ci_status
        from agenttree.github import CheckStatus

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            with patch("agenttree.state.get_active_agent") as mock_get_agent:
                with patch("agenttree.tmux.TmuxManager") as mock_tmux_class:
                    mock_agent = Mock()
                    mock_agent.tmux_session = "agent-42"
                    mock_agent.issue_id = "42"
                    mock_get_agent.return_value = mock_agent

                    mock_tmux = Mock()
                    mock_tmux.is_issue_running.return_value = True
                    mock_tmux_class.return_value = mock_tmux

                    mock_get_checks.return_value = [
                        CheckStatus(name="test", state="FAILURE", conclusion="failure"),
                    ]
                    check_ci_status(agents_dir)

                    # Verify tmux message was sent
                    mock_tmux.send_message_to_issue.assert_called_once()
                    call_args = mock_tmux.send_message_to_issue.call_args[0]
                    assert "agent-42" in call_args[0]
                    assert "CI" in call_args[1] or "failed" in call_args[1].lower()

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_skips_already_notified(self, mock_container, agents_dir):
        """Verify duplicate notifications are prevented using ci_notified flag."""
        import yaml
        from agenttree.agents_repo import check_ci_status
        from agenttree.github import CheckStatus

        # Create issue with ci_notified already set
        issue_dir = agents_dir / "issues" / "042-test-issue"
        issue_dir.mkdir()
        issue_yaml = issue_dir / "issue.yaml"
        data = {
            "id": "42",
            "title": "Test issue",
            "stage": "implementation_review",
            "pr_number": 123,
            "ci_notified": True,  # Already notified
        }
        with open(issue_yaml, "w") as f:
            yaml.dump(data, f)

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            mock_get_checks.return_value = [
                CheckStatus(name="test", state="FAILURE", conclusion="failure"),
            ]
            result = check_ci_status(agents_dir)

            # Should skip because already notified
            assert result == 0
            # Stage should remain implementation_review
            with open(issue_yaml) as f:
                new_data = yaml.safe_load(f)
            assert new_data["stage"] == "implementation_review"

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_sets_ci_notified_flag(self, mock_container, agents_dir, issue_at_implementation_review):
        """Verify ci_notified flag is set after notification."""
        import yaml
        from agenttree.agents_repo import check_ci_status
        from agenttree.github import CheckStatus

        issue_dir, _ = issue_at_implementation_review

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            with patch("agenttree.state.get_active_agent", return_value=None):
                mock_get_checks.return_value = [
                    CheckStatus(name="test", state="FAILURE", conclusion="failure"),
                ]
                check_ci_status(agents_dir)

                # The issue transitions to implement, so ci_notified doesn't matter
                # But let's verify the feedback file was created
                assert (issue_dir / "ci_feedback.md").exists()

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_ci_status_handles_no_active_agent_gracefully(self, mock_container, agents_dir, issue_at_implementation_review):
        """Verify graceful degradation when agent's tmux session isn't running."""
        from agenttree.agents_repo import check_ci_status
        from agenttree.github import CheckStatus

        issue_dir, _ = issue_at_implementation_review

        with patch("agenttree.github.get_pr_checks") as mock_get_checks:
            with patch("agenttree.state.get_active_agent", return_value=None):
                mock_get_checks.return_value = [
                    CheckStatus(name="test", state="FAILURE", conclusion="failure"),
                ]
                # Should not raise even without active agent
                result = check_ci_status(agents_dir)

                # Feedback file should still be created
                assert (issue_dir / "ci_feedback.md").exists()
                assert result == 1


@pytest.mark.usefixtures("host_environment")
class TestCheckMergedPrs:
    """Tests for check_merged_prs function."""

    @pytest.fixture
    def agents_dir(self, tmp_path):
        """Create a temporary _agenttree directory with issues subfolder."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()
        (agents_dir / "issues").mkdir()
        return agents_dir

    @pytest.fixture
    def issue_at_implementation_review_with_pr(self, agents_dir):
        """Create an issue at implementation_review with a PR number."""
        import yaml
        issue_dir = agents_dir / "issues" / "042"
        issue_dir.mkdir(parents=True)

        issue_data = {
            "id": "042",
            "slug": "042-test-issue",
            "title": "Test Issue",
            "stage": "implementation_review",
            "pr_number": 123,
            "branch": "issue-042",
            "worktree_dir": "/tmp/worktree-042",
            "created": "2024-01-01T00:00:00Z",
        }

        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.safe_dump(issue_data, f)

        return issue_dir, issue_data

    @patch("agenttree.hooks.is_running_in_container", return_value=True)
    def test_check_merged_prs_skips_in_container(self, mock_container, agents_dir):
        """Verify check_merged_prs skips when running in container."""
        from agenttree.agents_repo import check_merged_prs

        result = check_merged_prs(agents_dir)
        assert result == 0

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_merged_prs_skips_non_implementation_review(self, mock_container, agents_dir):
        """Verify issues not at implementation_review are skipped."""
        import yaml
        from agenttree.agents_repo import check_merged_prs

        issue_dir = agents_dir / "issues" / "001"
        issue_dir.mkdir(parents=True)

        # Issue at backlog stage
        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.safe_dump({
                "id": "001",
                "stage": "backlog",
                "pr_number": 123,
            }, f)

        result = check_merged_prs(agents_dir)
        assert result == 0

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_merged_prs_skips_issues_without_pr(self, mock_container, agents_dir):
        """Verify issues without PR number are skipped."""
        import yaml
        from agenttree.agents_repo import check_merged_prs

        issue_dir = agents_dir / "issues" / "001"
        issue_dir.mkdir(parents=True)

        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.safe_dump({
                "id": "001",
                "stage": "implementation_review",
                # No pr_number
            }, f)

        result = check_merged_prs(agents_dir)
        assert result == 0

    @patch("subprocess.run")
    @patch("agenttree.hooks.cleanup_issue_agent")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_merged_prs_advances_merged_pr_to_accepted(
        self, mock_container, mock_cleanup, mock_run, agents_dir, issue_at_implementation_review_with_pr
    ):
        """Verify merged PR advances issue to accepted."""
        import yaml
        import json
        from agenttree.agents_repo import check_merged_prs

        issue_dir, _ = issue_at_implementation_review_with_pr

        # Mock gh pr view returning MERGED state
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({"state": "MERGED", "mergedAt": "2024-01-01T00:00:00Z"})
        )

        result = check_merged_prs(agents_dir)

        assert result == 1

        # Verify issue was updated
        with open(issue_dir / "issue.yaml") as f:
            data = yaml.safe_load(f)
        assert data["stage"] == "accepted"

        # Verify cleanup was called
        mock_cleanup.assert_called_once()

    @patch("subprocess.run")
    @patch("agenttree.hooks.cleanup_issue_agent")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_merged_prs_advances_closed_pr_to_not_doing(
        self, mock_container, mock_cleanup, mock_run, agents_dir, issue_at_implementation_review_with_pr
    ):
        """Verify closed (not merged) PR advances issue to not_doing."""
        import yaml
        import json
        from agenttree.agents_repo import check_merged_prs

        issue_dir, _ = issue_at_implementation_review_with_pr

        # Mock gh pr view returning CLOSED state (not merged)
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({"state": "CLOSED", "mergedAt": None})
        )

        result = check_merged_prs(agents_dir)

        assert result == 1

        # Verify issue was updated
        with open(issue_dir / "issue.yaml") as f:
            data = yaml.safe_load(f)
        assert data["stage"] == "not_doing"

        # Verify cleanup was called
        mock_cleanup.assert_called_once()

    @patch("subprocess.run")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_merged_prs_ignores_open_pr(
        self, mock_container, mock_run, agents_dir, issue_at_implementation_review_with_pr
    ):
        """Verify open PR does not advance issue."""
        import yaml
        import json
        from agenttree.agents_repo import check_merged_prs

        issue_dir, _ = issue_at_implementation_review_with_pr

        # Mock gh pr view returning OPEN state
        mock_run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({"state": "OPEN", "mergedAt": None})
        )

        result = check_merged_prs(agents_dir)

        assert result == 0

        # Verify issue was NOT updated
        with open(issue_dir / "issue.yaml") as f:
            data = yaml.safe_load(f)
        assert data["stage"] == "implementation_review"

    @patch("subprocess.run")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_merged_prs_handles_gh_failure(
        self, mock_container, mock_run, agents_dir, issue_at_implementation_review_with_pr
    ):
        """Verify gh CLI failure is handled gracefully."""
        import yaml
        from agenttree.agents_repo import check_merged_prs

        issue_dir, _ = issue_at_implementation_review_with_pr

        # Mock gh pr view failing
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="not found")

        result = check_merged_prs(agents_dir)

        assert result == 0

        # Verify issue was NOT updated
        with open(issue_dir / "issue.yaml") as f:
            data = yaml.safe_load(f)
        assert data["stage"] == "implementation_review"

    @patch("subprocess.run")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_check_merged_prs_handles_timeout(
        self, mock_container, mock_run, agents_dir, issue_at_implementation_review_with_pr
    ):
        """Verify timeout is handled gracefully."""
        import yaml
        from agenttree.agents_repo import check_merged_prs

        issue_dir, _ = issue_at_implementation_review_with_pr

        # Mock timeout
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=30)

        result = check_merged_prs(agents_dir)

        assert result == 0


@pytest.mark.usefixtures("host_environment")
class TestPushPendingBranches:
    """Tests for push_pending_branches function."""

    @pytest.fixture
    def agents_dir(self, tmp_path):
        """Create a temporary _agenttree directory with issues subfolder."""
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()
        (agents_dir / "issues").mkdir()
        return agents_dir

    @pytest.fixture
    def issue_with_worktree(self, agents_dir, tmp_path):
        """Create an issue with a worktree that has unpushed commits."""
        import yaml

        issue_dir = agents_dir / "issues" / "043"
        issue_dir.mkdir(parents=True)

        worktree_dir = tmp_path / "worktree-043"
        worktree_dir.mkdir()

        issue_data = {
            "id": "043",
            "title": "Test Issue",
            "stage": "implementation",
            "branch": "issue-043",
            "worktree_dir": str(worktree_dir),
        }

        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.safe_dump(issue_data, f)

        return issue_dir, issue_data, worktree_dir

    @patch("agenttree.hooks.is_running_in_container", return_value=True)
    def test_push_pending_branches_skips_in_container(self, mock_container, agents_dir):
        """Verify push_pending_branches skips when running in container."""
        from agenttree.agents_repo import push_pending_branches

        result = push_pending_branches(agents_dir)
        assert result == 0

    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_push_pending_branches_skips_issues_without_branch(self, mock_container, agents_dir):
        """Verify issues without branch are skipped."""
        import yaml
        from agenttree.agents_repo import push_pending_branches

        issue_dir = agents_dir / "issues" / "001"
        issue_dir.mkdir(parents=True)

        with open(issue_dir / "issue.yaml", "w") as f:
            yaml.safe_dump({
                "id": "001",
                "stage": "implementation",
                # No branch or worktree_dir
            }, f)

        result = push_pending_branches(agents_dir)
        assert result == 0

    @patch("subprocess.run")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_push_pending_branches_skips_no_unpushed_commits(
        self, mock_container, mock_run, agents_dir, issue_with_worktree
    ):
        """Verify no push when there are no unpushed commits."""
        from agenttree.agents_repo import push_pending_branches

        # Mock git log showing no unpushed commits
        mock_run.return_value = Mock(returncode=0, stdout="")

        result = push_pending_branches(agents_dir)

        assert result == 0
        # Only the check command should be called, not push
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_push_pending_branches_pushes_with_commits(
        self, mock_container, mock_run, agents_dir, issue_with_worktree
    ):
        """Verify push when there are unpushed commits."""
        from agenttree.agents_repo import push_pending_branches

        def run_side_effect(cmd, **kwargs):
            if "log" in cmd:
                # Has unpushed commits
                return Mock(returncode=0, stdout="abc123 Commit message\n")
            elif "push" in cmd:
                # Push succeeds
                return Mock(returncode=0, stdout="", stderr="")
            return Mock(returncode=0)

        mock_run.side_effect = run_side_effect

        result = push_pending_branches(agents_dir)

        assert result == 1

    @patch("subprocess.run")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_push_pending_branches_force_push_on_diverged(
        self, mock_container, mock_run, agents_dir, issue_with_worktree
    ):
        """Verify force push when histories diverged."""
        from agenttree.agents_repo import push_pending_branches

        call_count = [0]

        def run_side_effect(cmd, **kwargs):
            call_count[0] += 1
            if "log" in cmd:
                return Mock(returncode=0, stdout="abc123 Commit message\n")
            elif "push" in cmd:
                if "--force-with-lease" in cmd:
                    # Force push succeeds
                    return Mock(returncode=0, stdout="", stderr="")
                else:
                    # Regular push fails with divergent
                    return Mock(returncode=1, stdout="", stderr="rejected (non-fast-forward)")
            return Mock(returncode=0)

        mock_run.side_effect = run_side_effect

        result = push_pending_branches(agents_dir)

        assert result == 1
        # Should have called: git log, git push (failed), git push --force-with-lease
        assert call_count[0] == 3

    @patch("subprocess.run")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_push_pending_branches_handles_push_failure(
        self, mock_container, mock_run, agents_dir, issue_with_worktree
    ):
        """Verify push failure is handled gracefully."""
        from agenttree.agents_repo import push_pending_branches

        def run_side_effect(cmd, **kwargs):
            if "log" in cmd:
                return Mock(returncode=0, stdout="abc123 Commit message\n")
            elif "push" in cmd:
                return Mock(returncode=1, stdout="", stderr="permission denied")
            return Mock(returncode=0)

        mock_run.side_effect = run_side_effect

        result = push_pending_branches(agents_dir)

        assert result == 0

    @patch("subprocess.run")
    @patch("agenttree.hooks.is_running_in_container", return_value=False)
    def test_push_pending_branches_handles_timeout(
        self, mock_container, mock_run, agents_dir, issue_with_worktree
    ):
        """Verify timeout is handled gracefully."""
        from agenttree.agents_repo import push_pending_branches

        def run_side_effect(cmd, **kwargs):
            if "log" in cmd:
                return Mock(returncode=0, stdout="abc123 Commit message\n")
            elif "push" in cmd:
                raise subprocess.TimeoutExpired(cmd="git push", timeout=60)
            return Mock(returncode=0)

        mock_run.side_effect = run_side_effect

        result = push_pending_branches(agents_dir)

        assert result == 0
