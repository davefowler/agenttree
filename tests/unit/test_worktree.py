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
