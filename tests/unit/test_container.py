"""Tests for container runtime support."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agenttree.container import ContainerRuntime, get_git_worktree_info


class TestBuildRunCommand:
    """Tests for ContainerRuntime.build_run_command credential handling."""

    @pytest.fixture
    def runtime(self):
        """Create a ContainerRuntime with mocked docker detection."""
        with patch.object(ContainerRuntime, 'detect_runtime', return_value='docker'):
            return ContainerRuntime()

    @pytest.fixture
    def tmp_worktree(self, tmp_path: Path) -> Path:
        """Create a temporary worktree directory."""
        worktree = tmp_path / "test-worktree"
        worktree.mkdir()
        return worktree

    def test_does_not_pass_anthropic_api_key(
        self, runtime: ContainerRuntime, tmp_worktree: Path
    ) -> None:
        """Test that ANTHROPIC_API_KEY is NOT passed to containers.

        Even when ANTHROPIC_API_KEY is set in the environment, it should
        not be included in the container command. Only CLAUDE_CODE_OAUTH_TOKEN
        should be used for container authentication.
        """
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'sk-ant-api03-test-key',
            'CLAUDE_CODE_OAUTH_TOKEN': 'sk-ant-oat01-test-token',
        }, clear=False):
            with patch.object(Path, 'home', return_value=tmp_worktree.parent):
                cmd = runtime.build_run_command(tmp_worktree)

        # Convert to string for easier searching
        cmd_str = ' '.join(cmd)

        # ANTHROPIC_API_KEY should NOT be in the command
        assert 'ANTHROPIC_API_KEY' not in cmd_str
        assert 'sk-ant-api03-test-key' not in cmd_str

    def test_passes_oauth_token_when_set(
        self, runtime: ContainerRuntime, tmp_worktree: Path
    ) -> None:
        """Test that CLAUDE_CODE_OAUTH_TOKEN is passed to containers when set."""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_OAUTH_TOKEN': 'sk-ant-oat01-test-token',
        }, clear=False):
            # Clear ANTHROPIC_API_KEY if set
            env = os.environ.copy()
            env.pop('ANTHROPIC_API_KEY', None)
            with patch.dict(os.environ, env, clear=True):
                with patch.object(Path, 'home', return_value=tmp_worktree.parent):
                    cmd = runtime.build_run_command(tmp_worktree)

        # Find the OAuth token in the command
        assert '-e' in cmd
        oauth_found = False
        for i, arg in enumerate(cmd):
            if arg == '-e' and i + 1 < len(cmd):
                if 'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-test-token' in cmd[i + 1]:
                    oauth_found = True
                    break

        assert oauth_found, "CLAUDE_CODE_OAUTH_TOKEN should be passed to container"

    def test_no_credentials_when_none_set(
        self, runtime: ContainerRuntime, tmp_worktree: Path
    ) -> None:
        """Test that no credential env vars are added when nothing is set."""
        # Create empty environment without credentials
        clean_env = {k: v for k, v in os.environ.items()
                     if k not in ('ANTHROPIC_API_KEY', 'CLAUDE_CODE_OAUTH_TOKEN')}

        with patch.dict(os.environ, clean_env, clear=True):
            with patch.object(Path, 'home', return_value=tmp_worktree.parent):
                cmd = runtime.build_run_command(tmp_worktree)

        cmd_str = ' '.join(cmd)

        # Neither credential should be in the command
        assert 'ANTHROPIC_API_KEY' not in cmd_str
        assert 'CLAUDE_CODE_OAUTH_TOKEN' not in cmd_str


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


    def test_port_exposure_adds_p_flag(
        self, runtime: ContainerRuntime, tmp_worktree: Path
    ) -> None:
        """Test that port parameter adds -p flag for port mapping."""
        with patch.object(Path, 'home', return_value=tmp_worktree.parent):
            cmd = runtime.build_run_command(tmp_worktree, port=9001)

        # Check that -p flag is present with correct port mapping
        assert '-p' in cmd
        port_idx = cmd.index('-p')
        assert cmd[port_idx + 1] == '9001:9001'

    def test_no_port_exposure_without_port_param(
        self, runtime: ContainerRuntime, tmp_worktree: Path
    ) -> None:
        """Test that -p flag is not added when port is None."""
        with patch.object(Path, 'home', return_value=tmp_worktree.parent):
            cmd = runtime.build_run_command(tmp_worktree, port=None)

        # Check that -p flag is not present
        assert '-p' not in cmd


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
