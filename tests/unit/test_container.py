"""Tests for container runtime support."""

from pathlib import Path
from unittest.mock import patch

import pytest

from agenttree.container import ContainerRuntime, get_git_worktree_info


class TestGetGitWorktreeInfo:
    """Tests for get_git_worktree_info function."""

    def test_returns_none_for_nonexistent_path(self, tmp_path: Path) -> None:
        """Test that non-existent paths return (None, None)."""
        nonexistent = tmp_path / "does-not-exist"
        main_dir, worktree_dir = get_git_worktree_info(nonexistent)
        assert main_dir is None
        assert worktree_dir is None

    def test_returns_none_for_regular_git_repo(self, tmp_path: Path) -> None:
        """Test that regular git repos (not worktrees) return (None, None)."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        main_dir, worktree_dir = get_git_worktree_info(tmp_path)
        assert main_dir is None
        assert worktree_dir is None

    def test_returns_paths_for_worktree(self, tmp_path: Path) -> None:
        """Test that worktrees return correct git directory paths."""
        # Simulate a worktree structure
        main_repo = tmp_path / "main-repo"
        main_git = main_repo / ".git"
        main_git.mkdir(parents=True)

        worktrees_dir = main_git / "worktrees" / "agent-1"
        worktrees_dir.mkdir(parents=True)

        # Create the worktree directory with .git file
        worktree = tmp_path / "worktree-1"
        worktree.mkdir()
        git_file = worktree / ".git"
        git_file.write_text(f"gitdir: {worktrees_dir}")

        main_dir, worktree_dir = get_git_worktree_info(worktree)
        assert main_dir == main_git
        assert worktree_dir == worktrees_dir


class TestContainerRuntimeDetection:
    """Tests for container runtime detection."""

    def test_detect_runtime_returns_docker_on_linux(self) -> None:
        """Test that docker is detected on Linux when available."""
        with patch('platform.system', return_value='Linux'):
            with patch('shutil.which', side_effect=lambda x: '/usr/bin/docker' if x == 'docker' else None):
                runtime = ContainerRuntime.detect_runtime()
                assert runtime == 'docker'

    def test_detect_runtime_returns_none_when_nothing_available(self) -> None:
        """Test that None is returned when no runtime is available."""
        with patch('platform.system', return_value='Linux'):
            with patch('shutil.which', return_value=None):
                runtime = ContainerRuntime.detect_runtime()
                assert runtime is None
