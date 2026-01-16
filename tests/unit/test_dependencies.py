"""Tests for dependency checking module."""

import subprocess
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from agenttree.dependencies import (
    DependencyResult,
    check_git_repo,
    check_gh_installed,
    check_gh_authenticated,
    check_container_runtime,
    check_all_dependencies,
    print_dependency_report,
)


class TestDependencyResult:
    """Tests for DependencyResult dataclass."""

    def test_create_passing_result(self):
        result = DependencyResult(
            name="test",
            passed=True,
            description="Test passed",
        )
        assert result.name == "test"
        assert result.passed is True
        assert result.description == "Test passed"
        assert result.fix_instructions is None
        assert result.required is True

    def test_create_failing_result_with_fix(self):
        result = DependencyResult(
            name="test",
            passed=False,
            description="Test failed",
            fix_instructions="Run this command",
            required=True,
        )
        assert result.passed is False
        assert result.fix_instructions == "Run this command"

    def test_create_warning_result(self):
        result = DependencyResult(
            name="container",
            passed=False,
            description="No container runtime",
            fix_instructions="Install Docker",
            required=False,  # Warning only
        )
        assert result.required is False


class TestCheckGitRepo:
    """Tests for check_git_repo function."""

    def test_check_git_repo_success(self, tmp_path: Path):
        """Test that check passes when .git directory exists."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        result = check_git_repo(tmp_path)

        assert result.passed is True
        assert result.name == "git_repo"
        assert "Git repository" in result.description

    def test_check_git_repo_failure(self, tmp_path: Path):
        """Test that check fails when .git directory is missing."""
        result = check_git_repo(tmp_path)

        assert result.passed is False
        assert result.name == "git_repo"
        assert "Not a git repository" in result.description
        assert result.fix_instructions is not None
        assert "git init" in result.fix_instructions


class TestCheckGhInstalled:
    """Tests for check_gh_installed function."""

    def test_check_gh_installed_success(self):
        """Test that check passes when gh CLI is found."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = "/usr/local/bin/gh"

            result = check_gh_installed()

            assert result.passed is True
            assert result.name == "gh_installed"
            assert "GitHub CLI" in result.description

    def test_check_gh_installed_failure(self):
        """Test that check fails when gh CLI is not found."""
        with patch("shutil.which") as mock_which:
            mock_which.return_value = None

            result = check_gh_installed()

            assert result.passed is False
            assert result.name == "gh_installed"
            assert "not installed" in result.description.lower()
            assert result.fix_instructions is not None
            assert "https://cli.github.com" in result.fix_instructions


class TestCheckGhAuthenticated:
    """Tests for check_gh_authenticated function."""

    def test_check_gh_authenticated_success(self):
        """Test that check passes when gh auth status returns 0."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=0, stdout="Logged in")

            result = check_gh_authenticated()

            assert result.passed is True
            assert result.name == "gh_authenticated"
            assert "authenticated" in result.description.lower()

    def test_check_gh_authenticated_failure(self):
        """Test that check fails when gh auth status returns non-zero."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = Mock(returncode=1, stderr="Not logged in")

            result = check_gh_authenticated()

            assert result.passed is False
            assert result.name == "gh_authenticated"
            assert "not authenticated" in result.description.lower()
            assert result.fix_instructions is not None
            assert "gh auth login" in result.fix_instructions

    def test_check_gh_authenticated_timeout(self):
        """Test that check handles timeout gracefully."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="gh", timeout=5)

            result = check_gh_authenticated()

            assert result.passed is False
            assert "timeout" in result.description.lower() or "timed out" in result.description.lower()

    def test_check_gh_authenticated_file_not_found(self):
        """Test that check handles missing gh executable."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("gh not found")

            result = check_gh_authenticated()

            assert result.passed is False


class TestCheckContainerRuntime:
    """Tests for check_container_runtime function."""

    def test_check_container_runtime_docker(self):
        """Test that check passes when Docker is available."""
        with patch("agenttree.dependencies.ContainerRuntime") as mock_runtime_class:
            mock_runtime = Mock()
            mock_runtime.is_available.return_value = True
            mock_runtime.get_runtime_name.return_value = "docker"
            mock_runtime_class.return_value = mock_runtime

            result = check_container_runtime()

            assert result.passed is True
            assert result.name == "container_runtime"
            assert "docker" in result.description.lower()
            assert result.required is False  # Container is a warning

    def test_check_container_runtime_apple(self):
        """Test that check passes when Apple Containers is available."""
        with patch("agenttree.dependencies.ContainerRuntime") as mock_runtime_class:
            mock_runtime = Mock()
            mock_runtime.is_available.return_value = True
            mock_runtime.get_runtime_name.return_value = "container"
            mock_runtime_class.return_value = mock_runtime

            result = check_container_runtime()

            assert result.passed is True
            assert "container" in result.description.lower()
            assert result.required is False

    def test_check_container_runtime_none(self):
        """Test that check returns warning when no runtime is available."""
        with patch("agenttree.dependencies.ContainerRuntime") as mock_runtime_class:
            mock_runtime = Mock()
            mock_runtime.is_available.return_value = False
            mock_runtime.get_runtime_name.return_value = "none"
            mock_runtime.get_recommended_action.return_value = "Install Docker"
            mock_runtime_class.return_value = mock_runtime

            result = check_container_runtime()

            assert result.passed is False
            assert result.name == "container_runtime"
            assert result.required is False  # Warning only, not a failure
            assert result.fix_instructions is not None


class TestCheckAllDependencies:
    """Tests for check_all_dependencies function."""

    def test_check_all_all_pass(self, tmp_path: Path):
        """Test that success is returned when all checks pass."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        with patch("shutil.which") as mock_which, \
             patch("subprocess.run") as mock_run, \
             patch("agenttree.dependencies.ContainerRuntime") as mock_runtime_class:
            mock_which.return_value = "/usr/local/bin/gh"
            mock_run.return_value = Mock(returncode=0, stdout="Logged in")
            mock_runtime = Mock()
            mock_runtime.is_available.return_value = True
            mock_runtime.get_runtime_name.return_value = "docker"
            mock_runtime_class.return_value = mock_runtime

            success, results = check_all_dependencies(tmp_path)

            assert success is True
            assert len(results) >= 3  # At least git, gh, gh_auth
            required_checks = [r for r in results if r.required]
            assert all(r.passed for r in required_checks)

    def test_check_all_one_failure(self, tmp_path: Path):
        """Test that failure is returned when a required check fails."""
        # No .git directory - git check will fail
        with patch("shutil.which") as mock_which, \
             patch("subprocess.run") as mock_run, \
             patch("agenttree.dependencies.ContainerRuntime") as mock_runtime_class:
            mock_which.return_value = "/usr/local/bin/gh"
            mock_run.return_value = Mock(returncode=0)
            mock_runtime = Mock()
            mock_runtime.is_available.return_value = True
            mock_runtime.get_runtime_name.return_value = "docker"
            mock_runtime_class.return_value = mock_runtime

            success, results = check_all_dependencies(tmp_path)

            assert success is False
            # Find the git check result
            git_result = next((r for r in results if r.name == "git_repo"), None)
            assert git_result is not None
            assert git_result.passed is False

    def test_check_all_multiple_failures(self, tmp_path: Path):
        """Test that all failures are collected and returned."""
        # No .git, no gh
        with patch("shutil.which") as mock_which, \
             patch("agenttree.dependencies.ContainerRuntime") as mock_runtime_class:
            mock_which.return_value = None  # gh not installed
            mock_runtime = Mock()
            mock_runtime.is_available.return_value = False
            mock_runtime.get_runtime_name.return_value = "none"
            mock_runtime.get_recommended_action.return_value = "Install Docker"
            mock_runtime_class.return_value = mock_runtime

            success, results = check_all_dependencies(tmp_path)

            assert success is False
            # Should have multiple failures
            failed_required = [r for r in results if r.required and not r.passed]
            assert len(failed_required) >= 2  # git and gh_installed at least

    def test_check_all_container_warning_not_fatal(self, tmp_path: Path):
        """Test that container check failure doesn't block success."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        with patch("shutil.which") as mock_which, \
             patch("subprocess.run") as mock_run, \
             patch("agenttree.dependencies.ContainerRuntime") as mock_runtime_class:
            mock_which.return_value = "/usr/local/bin/gh"
            mock_run.return_value = Mock(returncode=0)
            mock_runtime = Mock()
            mock_runtime.is_available.return_value = False  # No container
            mock_runtime.get_runtime_name.return_value = "none"
            mock_runtime.get_recommended_action.return_value = "Install Docker"
            mock_runtime_class.return_value = mock_runtime

            success, results = check_all_dependencies(tmp_path)

            # Should still succeed because container is a warning
            assert success is True
            container_result = next((r for r in results if r.name == "container_runtime"), None)
            assert container_result is not None
            assert container_result.passed is False
            assert container_result.required is False

    def test_check_all_skips_auth_when_gh_missing(self, tmp_path: Path):
        """Test that gh auth check is skipped when gh is not installed."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        with patch("shutil.which") as mock_which, \
             patch("subprocess.run") as mock_run, \
             patch("agenttree.dependencies.ContainerRuntime") as mock_runtime_class:
            mock_which.return_value = None  # gh not installed
            mock_runtime = Mock()
            mock_runtime.is_available.return_value = True
            mock_runtime.get_runtime_name.return_value = "docker"
            mock_runtime_class.return_value = mock_runtime

            success, results = check_all_dependencies(tmp_path)

            # gh_authenticated should be skipped (not in results) or marked as skipped
            auth_result = next((r for r in results if r.name == "gh_authenticated"), None)
            # Either not present or marked as skipped
            if auth_result is not None:
                # If present, it should indicate it was skipped
                assert "skipped" in auth_result.description.lower() or not auth_result.required
            # subprocess.run should not have been called for auth
            # (it would fail since gh is not installed)


class TestPrintDependencyReport:
    """Tests for print_dependency_report function."""

    def test_format_results_shows_all(self, capsys):
        """Test that report displays both passed and failed checks."""
        results = [
            DependencyResult(
                name="git_repo",
                passed=True,
                description="Git repository detected",
            ),
            DependencyResult(
                name="gh_installed",
                passed=False,
                description="GitHub CLI not installed",
                fix_instructions="Install from https://cli.github.com",
            ),
        ]

        print_dependency_report(results)
        captured = capsys.readouterr()

        # Both results should appear in output
        assert "git" in captured.out.lower()
        assert "github cli" in captured.out.lower()

    def test_format_results_failure_includes_fix(self, capsys):
        """Test that failed checks show fix instructions."""
        results = [
            DependencyResult(
                name="gh_installed",
                passed=False,
                description="GitHub CLI not installed",
                fix_instructions="Install from https://cli.github.com",
            ),
        ]

        print_dependency_report(results)
        captured = capsys.readouterr()

        assert "https://cli.github.com" in captured.out
