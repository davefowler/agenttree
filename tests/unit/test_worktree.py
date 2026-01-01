"""Tests for git worktree management."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, call
import pytest

from agenttree.worktree import (
    WorktreeManager,
    WorktreeStatus,
    is_busy,
    create_worktree,
    remove_worktree,
    reset_worktree,
    list_worktrees,
)
from agenttree.config import Config


class TestWorktreeStatus:
    """Tests for WorktreeStatus model."""

    def test_worktree_status_creation(self) -> None:
        """Test creating a worktree status object."""
        status = WorktreeStatus(
            agent_num=1,
            path=Path("/tmp/agent-1"),
            branch="agent-1-work",
            has_task=True,
            has_uncommitted=False,
            is_busy=True,
        )
        assert status.agent_num == 1
        assert status.path == Path("/tmp/agent-1")
        assert status.branch == "agent-1-work"
        assert status.has_task is True
        assert status.has_uncommitted is False
        assert status.is_busy is True


class TestIsBusy:
    """Tests for busy detection."""

    def test_busy_with_task_file(self, tmp_path: Path) -> None:
        """Test agent is busy when TASK.md exists."""
        task_file = tmp_path / "TASK.md"
        task_file.write_text("# Task\nDo something")

        assert is_busy(tmp_path) is True

    def test_busy_with_uncommitted_changes(self, tmp_path: Path) -> None:
        """Test agent is busy with uncommitted changes."""
        # Mock git status to show changes
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=" M file.py\n", returncode=0
            )
            assert is_busy(tmp_path) is True

    def test_not_busy(self, tmp_path: Path) -> None:
        """Test agent is not busy."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(stdout="", returncode=0)
            assert is_busy(tmp_path) is False

    def test_busy_with_both_conditions(self, tmp_path: Path) -> None:
        """Test agent is busy with both task file and uncommitted changes."""
        task_file = tmp_path / "TASK.md"
        task_file.write_text("# Task")

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(
                stdout=" M file.py\n", returncode=0
            )
            assert is_busy(tmp_path) is True


class TestCreateWorktree:
    """Tests for creating worktrees."""

    @patch("subprocess.run")
    def test_create_worktree_new_branch(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test creating a new worktree with a new branch."""
        mock_run.return_value = Mock(returncode=0)

        worktree_path = tmp_path / "agent-1"
        create_worktree(tmp_path, worktree_path, "agent-1-work")

        # Verify git commands were called
        calls = [c[0][0] for c in mock_run.call_args_list]  # Get the command lists

        # Should call git branch and git worktree add
        assert any("branch" in call for call in calls)
        assert any("worktree" in call and "add" in call for call in calls)

    @patch("subprocess.run")
    def test_create_worktree_existing_branch(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test creating worktree when branch already exists."""
        # First call (git branch) fails because branch exists
        # Second call (git worktree add) succeeds
        mock_run.side_effect = [
            subprocess.CalledProcessError(1, "git branch"),
            Mock(returncode=0),
        ]

        worktree_path = tmp_path / "agent-1"
        create_worktree(tmp_path, worktree_path, "agent-1-work")

        # Should still succeed
        assert mock_run.call_count == 2


class TestRemoveWorktree:
    """Tests for removing worktrees."""

    @patch("subprocess.run")
    def test_remove_worktree(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test removing a worktree."""
        mock_run.return_value = Mock(returncode=0)

        worktree_path = tmp_path / "agent-1"
        remove_worktree(tmp_path, worktree_path)

        # Verify git worktree remove was called
        mock_run.assert_called_once()
        call_cmd = mock_run.call_args[0][0]
        assert call_cmd[0:3] == ["git", "worktree", "remove"]

    @patch("subprocess.run")
    def test_remove_nonexistent_worktree(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test removing a worktree that doesn't exist."""
        mock_run.side_effect = subprocess.CalledProcessError(1, "git worktree remove")

        worktree_path = tmp_path / "agent-99"

        # Should not raise an error
        remove_worktree(tmp_path, worktree_path)


class TestResetWorktree:
    """Tests for resetting worktrees."""

    @patch("subprocess.run")
    def test_reset_worktree(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test resetting worktree to latest main."""
        mock_run.return_value = Mock(returncode=0)

        # Create TASK.md file
        task_file = tmp_path / "TASK.md"
        task_file.write_text("# Old task")

        reset_worktree(tmp_path, "main")

        # Verify git commands were called
        calls = [c[0][0] for c in mock_run.call_args_list]  # Get the command lists

        assert any("fetch" in call for call in calls)
        assert any("reset" in call for call in calls)
        assert any("clean" in call for call in calls)

        # Verify TASK.md was removed
        assert not task_file.exists()

    @patch("subprocess.run")
    def test_reset_worktree_custom_branch(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test resetting worktree to a custom branch."""
        mock_run.return_value = Mock(returncode=0)

        reset_worktree(tmp_path, "develop")

        # Verify checkout to develop branch
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("develop" in c for c in calls)


class TestListWorktrees:
    """Tests for listing worktrees."""

    @patch("subprocess.run")
    def test_list_worktrees(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test listing all git worktrees."""
        # Mock git worktree list output
        mock_output = (
            "/home/user/project/  abc123 [main]\n"
            "/tmp/agent-1         def456 [agent-1-work]\n"
            "/tmp/agent-2         ghi789 [agent-2-work]\n"
        )
        mock_run.return_value = Mock(stdout=mock_output, returncode=0)

        worktrees = list_worktrees(tmp_path)

        assert len(worktrees) == 3
        assert worktrees[0]["path"] == "/home/user/project/"
        assert worktrees[0]["branch"] == "main"
        assert worktrees[1]["path"] == "/tmp/agent-1"
        assert worktrees[1]["branch"] == "agent-1-work"


class TestWorktreeManager:
    """Tests for WorktreeManager class."""

    def test_worktree_manager_init(self, tmp_path: Path) -> None:
        """Test initializing WorktreeManager."""
        config = Config(worktrees_dir=tmp_path)
        manager = WorktreeManager(tmp_path, config)

        assert manager.repo_path == tmp_path
        assert manager.config == config

    @patch("agenttree.worktree.create_worktree")
    def test_setup_agent(
        self, mock_create: Mock, tmp_path: Path
    ) -> None:
        """Test setting up an agent worktree."""
        config = Config(worktrees_dir=tmp_path)
        manager = WorktreeManager(tmp_path, config)

        manager.setup_agent(1)

        mock_create.assert_called_once()
        assert tmp_path / "agent-1" in mock_create.call_args[0]

    @patch("agenttree.worktree.is_busy")
    @patch("agenttree.worktree.reset_worktree")
    def test_dispatch_to_agent(
        self, mock_reset: Mock, mock_is_busy: Mock, tmp_path: Path
    ) -> None:
        """Test dispatching task to agent."""
        mock_is_busy.return_value = False
        config = Config(worktrees_dir=tmp_path)
        manager = WorktreeManager(tmp_path, config)

        worktree_path = tmp_path / "agent-1"
        worktree_path.mkdir(parents=True)

        manager.dispatch(1, "main")

        # Verify worktree was reset
        mock_reset.assert_called_once()

    @patch("agenttree.worktree.is_busy")
    def test_dispatch_to_busy_agent_without_force(
        self, mock_is_busy: Mock, tmp_path: Path
    ) -> None:
        """Test error when dispatching to busy agent without force flag."""
        mock_is_busy.return_value = True
        config = Config(worktrees_dir=tmp_path)
        manager = WorktreeManager(tmp_path, config)

        worktree_path = tmp_path / "agent-1"
        worktree_path.mkdir(parents=True)

        with pytest.raises(RuntimeError, match="Agent 1 is busy"):
            manager.dispatch(1, "main", force=False)

    @patch("agenttree.worktree.is_busy")
    @patch("agenttree.worktree.reset_worktree")
    def test_dispatch_to_busy_agent_with_force(
        self, mock_reset: Mock, mock_is_busy: Mock, tmp_path: Path
    ) -> None:
        """Test dispatching to busy agent with force flag."""
        mock_is_busy.return_value = True
        config = Config(worktrees_dir=tmp_path)
        manager = WorktreeManager(tmp_path, config)

        worktree_path = tmp_path / "agent-1"
        worktree_path.mkdir(parents=True)

        # Should not raise error with force=True
        manager.dispatch(1, "main", force=True)
        mock_reset.assert_called_once()

    @patch("agenttree.worktree.is_busy")
    def test_get_agent_status(self, mock_is_busy: Mock, tmp_path: Path) -> None:
        """Test getting agent status."""
        mock_is_busy.return_value = True
        config = Config(worktrees_dir=tmp_path)
        manager = WorktreeManager(tmp_path, config)

        worktree_path = tmp_path / "agent-1"
        worktree_path.mkdir(parents=True)

        # Create TASK.md
        task_file = worktree_path / "TASK.md"
        task_file.write_text("# Task")

        status = manager.get_status(1)

        assert status.agent_num == 1
        assert status.is_busy is True
        assert status.has_task is True

    def test_worktree_status_repr(self) -> None:
        """Test WorktreeStatus string representation."""
        # Test __repr__ method (lines 49-50 in coverage report)
        status = WorktreeStatus(
            agent_num=1,
            path=Path("/tmp/agent-1"),
            branch="agent-1-work",
            has_task=True,
            has_uncommitted=False,
            is_busy=True,
        )
        repr_str = repr(status)
        assert "WorktreeStatus" in repr_str
        assert "agent_num=1" in repr_str

    @patch("agenttree.worktree.subprocess.run")
    def test_is_busy_error_handling(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test is_busy handles subprocess errors gracefully."""
        # Test error handling in is_busy (lines 49-50: except block)
        # Simulate subprocess error
        mock_run.side_effect = FileNotFoundError("git not found")

        # Should return False on error, not raise
        result = is_busy(tmp_path)
        assert result is False

    @patch("agenttree.worktree.subprocess.run")
    def test_is_busy_subprocess_error(self, mock_run: Mock, tmp_path: Path) -> None:
        """Test is_busy handles CalledProcessError."""
        # Another test for the except block coverage
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        # Should return False on error
        result = is_busy(tmp_path)
        assert result is False


class TestCreateWorktreeErrors:
    """Tests for create_worktree error handling."""

    @patch("agenttree.worktree.subprocess.run")
    def test_create_worktree_when_worktree_add_fails(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test create_worktree when git worktree add fails (line 172)."""
        # First call (branch creation) succeeds
        # Second call (worktree add) fails
        mock_run.side_effect = [
            Mock(returncode=0),  # git branch succeeds
            subprocess.CalledProcessError(1, "git"),  # git worktree add fails
        ]

        worktree_path = tmp_path / "agent-1"

        # Should raise the error from git worktree add
        with pytest.raises(subprocess.CalledProcessError):
            create_worktree(tmp_path, worktree_path, "agent-1")


class TestRemoveWorktreeErrors:
    """Tests for remove_worktree error handling."""

    @patch("agenttree.worktree.subprocess.run")
    def test_remove_worktree_already_removed(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test remove_worktree when worktree doesn't exist (line 261)."""
        # Simulate worktree doesn't exist
        mock_run.side_effect = subprocess.CalledProcessError(1, "git")

        worktree_path = tmp_path / "agent-1"

        # Should not raise error, just silently succeed
        remove_worktree(tmp_path, worktree_path)  # Should not raise


class TestResetWorktreeErrors:
    """Tests for reset_worktree error handling."""

    @patch("agenttree.worktree.subprocess.run")
    def test_reset_worktree_checkout_fails_creates_branch(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test reset_worktree when checkout fails and creates branch from origin (lines 124-126)."""
        # git fetch succeeds, git checkout fails (branch doesn't exist locally),
        # then creates from origin
        mock_run.side_effect = [
            Mock(returncode=0),  # git fetch succeeds
            subprocess.CalledProcessError(1, "git checkout"),  # checkout fails
            Mock(returncode=0),  # git checkout -b from origin succeeds
            Mock(returncode=0),  # git reset succeeds
            Mock(returncode=0),  # git clean succeeds
        ]

        worktree_path = tmp_path / "agent-1"

        # Should not raise, creates branch from origin
        reset_worktree(worktree_path, "main")

        # Verify it tried to create branch from origin
        calls = [str(c) for c in mock_run.call_args_list]
        assert any("origin/main" in str(c) for c in calls)

    @patch("agenttree.worktree.subprocess.run")
    def test_reset_worktree_git_fetch_fails(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test reset_worktree when git fetch fails (lines 278-279)."""
        # git fetch fails
        mock_run.side_effect = subprocess.CalledProcessError(1, "git fetch")

        worktree_path = tmp_path / "agent-1"

        # Should raise the error
        with pytest.raises(subprocess.CalledProcessError):
            reset_worktree(worktree_path, "main")

    @patch("agenttree.worktree.subprocess.run")
    def test_reset_worktree_git_reset_fails(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test reset_worktree when git reset fails (lines 278-279)."""
        # git fetch succeeds, git reset fails
        mock_run.side_effect = [
            Mock(returncode=0),  # git fetch succeeds
            Mock(returncode=0),  # git checkout succeeds
            subprocess.CalledProcessError(1, "git reset"),  # git reset fails
        ]

        worktree_path = tmp_path / "agent-1"

        # Should raise the error from git reset
        with pytest.raises(subprocess.CalledProcessError):
            reset_worktree(worktree_path, "main")


class TestListWorktreesErrors:
    """Tests for list_worktrees error handling."""

    @patch("agenttree.worktree.subprocess.run")
    def test_list_worktrees_parsing_error(
        self, mock_run: Mock, tmp_path: Path
    ) -> None:
        """Test list_worktrees when parsing fails (line 299)."""
        # Return invalid output that can't be parsed
        mock_run.return_value = Mock(
            returncode=0,
            stdout="invalid output without proper format",
        )

        # Should handle parsing errors gracefully
        worktrees = list_worktrees(tmp_path)
        # Should return empty list or handle gracefully
        assert isinstance(worktrees, list)


class TestGetAgentStatusEdgeCases:
    """Tests for get_agent_status edge cases."""

    @patch("agenttree.worktree.list_worktrees")
    @patch("agenttree.worktree.is_busy")
    def test_get_status_worktree_not_found(
        self, mock_is_busy: Mock, mock_list: Mock, tmp_path: Path
    ) -> None:
        """Test get_status when worktree doesn't exist (lines 307-308)."""
        # No worktrees exist
        mock_list.return_value = []
        mock_is_busy.return_value = False

        config = Config(worktrees_dir=tmp_path)
        manager = WorktreeManager(tmp_path, config)

        # Worktree doesn't exist, but we still create a status
        status = manager.get_status(1)

        # Should still return a status object
        assert status.agent_num == 1
        assert status.has_task is False  # No TASK.md
        assert status.has_uncommitted is False
        assert status.is_busy is False

    @patch("agenttree.worktree.is_busy")
    def test_get_status_with_branch_info(
        self, mock_is_busy: Mock, tmp_path: Path
    ) -> None:
        """Test get_status extracts branch information (lines 307-308)."""
        # Test when worktree exists with branch info
        mock_is_busy.return_value = False

        config = Config(worktrees_dir=tmp_path)
        manager = WorktreeManager(tmp_path, config)

        worktree_path = tmp_path / "agent-1"
        worktree_path.mkdir(parents=True)

        # Create a .git file (worktree pointer)
        git_file = worktree_path / ".git"
        git_file.write_text("gitdir: /main/.git/worktrees/agent-1")

        status = manager.get_status(1)

        # Should have path set correctly
        assert status.path == worktree_path
        assert status.has_uncommitted is False
