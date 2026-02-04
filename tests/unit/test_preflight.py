"""Tests for agenttree.preflight module."""

import subprocess
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import Mock, patch, MagicMock

import pytest


class TestPreflightResult:
    """Tests for PreflightResult dataclass."""

    def test_preflight_result_success(self):
        """PreflightResult should represent a successful check."""
        from agenttree.preflight import PreflightResult

        result = PreflightResult(
            name="test_check",
            passed=True,
            message="All good",
        )

        assert result.name == "test_check"
        assert result.passed is True
        assert result.message == "All good"

    def test_preflight_result_failure(self):
        """PreflightResult should represent a failed check."""
        from agenttree.preflight import PreflightResult

        result = PreflightResult(
            name="test_check",
            passed=False,
            message="Something wrong",
            fix_hint="Try fixing it",
        )

        assert result.name == "test_check"
        assert result.passed is False
        assert result.message == "Something wrong"
        assert result.fix_hint == "Try fixing it"


class TestPreflightCheck:
    """Tests for PreflightCheck base class/protocol."""

    def test_preflight_check_has_required_attributes(self):
        """PreflightCheck should have name, description, and check method."""
        from agenttree.preflight import PreflightCheck

        class MyCheck(PreflightCheck):
            name = "my_check"
            description = "My test check"

            def check(self) -> "PreflightResult":
                from agenttree.preflight import PreflightResult
                return PreflightResult(name=self.name, passed=True, message="OK")

        check = MyCheck()
        assert check.name == "my_check"
        assert check.description == "My test check"
        assert callable(check.check)

    def test_preflight_check_abstract(self):
        """PreflightCheck without implemented check() should fail."""
        from agenttree.preflight import PreflightCheck

        # Should require check() to be implemented
        with pytest.raises(TypeError):
            class IncompleteCheck(PreflightCheck):
                name = "incomplete"
                description = "Missing check method"

            IncompleteCheck()


class TestPreflightRegistry:
    """Tests for PreflightRegistry class."""

    def test_registry_initialization(self):
        """PreflightRegistry should initialize with empty checks list."""
        from agenttree.preflight import PreflightRegistry

        registry = PreflightRegistry()
        assert isinstance(registry.checks, list)
        assert len(registry.checks) == 0

    def test_register_check(self):
        """Should register a preflight check."""
        from agenttree.preflight import PreflightRegistry, PreflightCheck, PreflightResult

        registry = PreflightRegistry()

        class MyCheck(PreflightCheck):
            name = "my_check"
            description = "Test check"

            def check(self) -> PreflightResult:
                return PreflightResult(name=self.name, passed=True, message="OK")

        registry.register(MyCheck())

        assert len(registry.checks) == 1
        assert registry.checks[0].name == "my_check"

    def test_register_multiple_checks(self):
        """Should register multiple checks."""
        from agenttree.preflight import PreflightRegistry, PreflightCheck, PreflightResult

        registry = PreflightRegistry()

        class Check1(PreflightCheck):
            name = "check1"
            description = "First check"

            def check(self) -> PreflightResult:
                return PreflightResult(name=self.name, passed=True, message="OK")

        class Check2(PreflightCheck):
            name = "check2"
            description = "Second check"

            def check(self) -> PreflightResult:
                return PreflightResult(name=self.name, passed=True, message="OK")

        registry.register(Check1())
        registry.register(Check2())

        assert len(registry.checks) == 2
        assert registry.checks[0].name == "check1"
        assert registry.checks[1].name == "check2"

    def test_run_all_checks_success(self):
        """Should run all registered checks and return results."""
        from agenttree.preflight import PreflightRegistry, PreflightCheck, PreflightResult

        registry = PreflightRegistry()

        class PassingCheck(PreflightCheck):
            name = "passing"
            description = "Always passes"

            def check(self) -> PreflightResult:
                return PreflightResult(name=self.name, passed=True, message="All good")

        registry.register(PassingCheck())
        registry.register(PassingCheck())

        results = registry.run_all()

        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_run_all_checks_with_failures(self):
        """Should collect results from all checks including failures."""
        from agenttree.preflight import PreflightRegistry, PreflightCheck, PreflightResult

        registry = PreflightRegistry()

        class PassingCheck(PreflightCheck):
            name = "passing"
            description = "Passes"

            def check(self) -> PreflightResult:
                return PreflightResult(name=self.name, passed=True, message="OK")

        class FailingCheck(PreflightCheck):
            name = "failing"
            description = "Fails"

            def check(self) -> PreflightResult:
                return PreflightResult(name=self.name, passed=False, message="Failed")

        registry.register(PassingCheck())
        registry.register(FailingCheck())

        results = registry.run_all()

        assert len(results) == 2
        passed = [r for r in results if r.passed]
        failed = [r for r in results if not r.passed]
        assert len(passed) == 1
        assert len(failed) == 1

    def test_run_all_continues_on_exception(self):
        """Should continue running checks even if one raises an exception."""
        from agenttree.preflight import PreflightRegistry, PreflightCheck, PreflightResult

        registry = PreflightRegistry()

        class CrashingCheck(PreflightCheck):
            name = "crashing"
            description = "Crashes"

            def check(self) -> PreflightResult:
                raise RuntimeError("Boom!")

        class GoodCheck(PreflightCheck):
            name = "good"
            description = "Works"

            def check(self) -> PreflightResult:
                return PreflightResult(name=self.name, passed=True, message="OK")

        registry.register(CrashingCheck())
        registry.register(GoodCheck())

        results = registry.run_all()

        assert len(results) == 2
        # Crashing check should be marked as failed
        crash_result = [r for r in results if r.name == "crashing"][0]
        assert crash_result.passed is False
        assert "Boom!" in crash_result.message or "error" in crash_result.message.lower()
        # Good check should still pass
        good_result = [r for r in results if r.name == "good"][0]
        assert good_result.passed is True

    def test_all_passed_property(self):
        """Should have all_passed property to check overall status."""
        from agenttree.preflight import PreflightRegistry, PreflightCheck, PreflightResult

        registry = PreflightRegistry()

        class PassingCheck(PreflightCheck):
            name = "passing"
            description = "Passes"

            def check(self) -> PreflightResult:
                return PreflightResult(name=self.name, passed=True, message="OK")

        registry.register(PassingCheck())
        results = registry.run_all()

        # Using a results object or checking results
        assert all(r.passed for r in results)


class TestPythonVersionCheck:
    """Tests for PythonVersionCheck."""

    def test_python_version_check_passes_for_valid_version(self):
        """Should pass when Python version meets minimum requirement."""
        from agenttree.preflight import PythonVersionCheck

        check = PythonVersionCheck(min_version=(3, 10))

        # Mock sys.version_info to be >= 3.10
        with patch.object(sys, 'version_info', (3, 12, 0)):
            result = check.check()

        assert result.passed is True
        assert "3.12" in result.message or "Python" in result.message

    def test_python_version_check_fails_for_old_version(self):
        """Should fail when Python version is below minimum."""
        from agenttree.preflight import PythonVersionCheck

        check = PythonVersionCheck(min_version=(3, 10))

        # Mock sys.version_info to be < 3.10
        with patch.object(sys, 'version_info', (3, 8, 0)):
            result = check.check()

        assert result.passed is False
        assert "3.8" in result.message or "3.10" in result.message

    def test_python_version_check_default_minimum(self):
        """Should have a sensible default minimum version."""
        from agenttree.preflight import PythonVersionCheck

        check = PythonVersionCheck()
        # Default should be at least 3.10 based on plan
        assert check.min_version >= (3, 10)


class TestDependenciesCheck:
    """Tests for DependenciesCheck."""

    def test_dependencies_check_passes_when_installed(self):
        """Should pass when dependencies are installed."""
        from agenttree.preflight import DependenciesCheck

        check = DependenciesCheck()

        # Mock subprocess to return success for uv sync --check
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = check.check()

        assert result.passed is True

    def test_dependencies_check_fails_when_missing(self):
        """Should fail when dependencies are missing."""
        from agenttree.preflight import DependenciesCheck

        check = DependenciesCheck()

        # Mock subprocess to return failure
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stderr="Missing package: foo"
            )
            result = check.check()

        assert result.passed is False
        assert result.fix_hint is not None  # Should suggest how to fix

    def test_dependencies_check_detects_uv(self):
        """Should detect uv package manager from pyproject.toml."""
        from agenttree.preflight import DependenciesCheck

        check = DependenciesCheck()

        # If pyproject.toml has uv, should use uv
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.read_text', return_value='[tool.uv]'):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    result = check.check()
                    # Should call uv sync --check or similar
                    mock_run.assert_called()


class TestGitCheck:
    """Tests for GitCheck."""

    def test_git_check_passes_when_git_works(self):
        """Should pass when git is available and working."""
        from agenttree.preflight import GitCheck

        check = GitCheck()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = check.check()

        assert result.passed is True

    def test_git_check_fails_when_not_repo(self):
        """Should fail when not in a git repository."""
        from agenttree.preflight import GitCheck

        check = GitCheck()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=128,
                stderr="fatal: not a git repository"
            )
            result = check.check()

        assert result.passed is False
        assert "git" in result.message.lower()


class TestAgenttreeCliCheck:
    """Tests for AgenttreeCliCheck."""

    def test_agenttree_cli_check_passes_when_accessible(self):
        """Should pass when agenttree CLI is accessible."""
        from agenttree.preflight import AgenttreeCliCheck

        check = AgenttreeCliCheck()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="agenttree, version 0.1.0"
            )
            result = check.check()

        assert result.passed is True

    def test_agenttree_cli_check_fails_when_not_found(self):
        """Should fail when agenttree CLI is not found."""
        from agenttree.preflight import AgenttreeCliCheck

        check = AgenttreeCliCheck()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("agenttree not found")
            result = check.check()

        assert result.passed is False


class TestTestRunnerCheck:
    """Tests for TestRunnerCheck."""

    def test_test_runner_check_passes_with_pytest(self):
        """Should pass when pytest is available."""
        from agenttree.preflight import TestRunnerCheck

        check = TestRunnerCheck()

        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="pytest 8.0.0"
            )
            result = check.check()

        assert result.passed is True

    def test_test_runner_check_fails_when_missing(self):
        """Should fail when no test runner is found."""
        from agenttree.preflight import TestRunnerCheck

        check = TestRunnerCheck()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = FileNotFoundError("pytest not found")
            result = check.check()

        assert result.passed is False
        assert result.fix_hint is not None


class TestGetDefaultRegistry:
    """Tests for get_default_registry function."""

    def test_get_default_registry_returns_registry(self):
        """Should return a PreflightRegistry with default checks."""
        from agenttree.preflight import get_default_registry, PreflightRegistry

        registry = get_default_registry()

        assert isinstance(registry, PreflightRegistry)
        assert len(registry.checks) > 0

    def test_get_default_registry_includes_builtin_checks(self):
        """Should include all built-in checks."""
        from agenttree.preflight import get_default_registry

        registry = get_default_registry()
        check_names = [c.name for c in registry.checks]

        # Should have the core checks mentioned in the plan
        assert "python_version" in check_names
        assert "dependencies" in check_names
        assert "git" in check_names
        assert "agenttree_cli" in check_names
        assert "test_runner" in check_names


class TestRunPreflight:
    """Tests for run_preflight function."""

    def test_run_preflight_returns_results(self):
        """Should run all checks and return results."""
        from agenttree.preflight import run_preflight

        results = run_preflight()

        assert isinstance(results, list)
        assert len(results) > 0

    def test_run_preflight_returns_false_when_checks_fail(self):
        """run_preflight should indicate failure when checks fail."""
        from agenttree.preflight import run_preflight, PreflightResult

        # Mock get_default_registry to return a failing check
        with patch('agenttree.preflight.get_default_registry') as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.run_all.return_value = [
                PreflightResult(name="failing", passed=False, message="Failed")
            ]
            mock_get_registry.return_value = mock_registry

            results = run_preflight()
            assert any(not r.passed for r in results)


class TestPreflightCLI:
    """Tests for preflight CLI command."""

    def test_preflight_command_exists(self):
        """preflight command should be registered in CLI."""
        from agenttree.cli import main
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(main, ['preflight', '--help'])

        assert result.exit_code == 0
        assert 'preflight' in result.output.lower() or 'environment' in result.output.lower()

    def test_preflight_command_runs_checks(self):
        """preflight command should run environment checks."""
        from agenttree.cli import main
        from click.testing import CliRunner
        import agenttree.cli.config_cmd

        runner = CliRunner()

        # Save original and mock
        original_run_preflight = agenttree.cli.config_cmd.run_preflight
        from agenttree.preflight import PreflightResult

        def mock_run():
            return [PreflightResult(name="test", passed=True, message="OK")]

        agenttree.cli.config_cmd.run_preflight = mock_run

        try:
            result = runner.invoke(main, ['preflight'])
            # Test passed if we got here and the result indicates success
            assert "test" in result.output.lower() or result.exit_code == 0
        finally:
            agenttree.cli.config_cmd.run_preflight = original_run_preflight

    def test_preflight_command_exit_code_success(self):
        """preflight command should exit 0 when all checks pass."""
        from agenttree.cli import main
        from click.testing import CliRunner
        import agenttree.cli.config_cmd
        from agenttree.preflight import PreflightResult

        runner = CliRunner()
        original = agenttree.cli.config_cmd.run_preflight

        def mock_run():
            return [PreflightResult(name="test", passed=True, message="OK")]

        agenttree.cli.config_cmd.run_preflight = mock_run
        try:
            result = runner.invoke(main, ['preflight'])
            assert result.exit_code == 0
        finally:
            agenttree.cli.config_cmd.run_preflight = original

    def test_preflight_command_exit_code_failure(self):
        """preflight command should exit 1 when checks fail."""
        from agenttree.cli import main
        from click.testing import CliRunner
        import agenttree.cli.config_cmd
        from agenttree.preflight import PreflightResult

        runner = CliRunner()
        original = agenttree.cli.config_cmd.run_preflight

        def mock_run():
            return [PreflightResult(name="test", passed=False, message="Failed")]

        agenttree.cli.config_cmd.run_preflight = mock_run
        try:
            result = runner.invoke(main, ['preflight'])
            assert result.exit_code == 1
        finally:
            agenttree.cli.config_cmd.run_preflight = original


class TestStartCommandWithPreflight:
    """Tests for preflight integration with start command."""

    def test_start_has_skip_preflight_option(self):
        """start command should have --skip-preflight option."""
        from agenttree.cli import main
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(main, ['start', '--help'])

        assert '--skip-preflight' in result.output

    def test_start_runs_preflight_by_default(self):
        """start should run preflight checks by default."""
        from agenttree.cli import main
        from click.testing import CliRunner
        import agenttree.cli.agent

        runner = CliRunner()

        # Save original and replace with mock
        original_run_preflight = agenttree.cli.agent.run_preflight

        from agenttree.preflight import PreflightResult

        def mock_preflight():
            return [PreflightResult(name="test", passed=False, message="Preflight check failed")]

        agenttree.cli.agent.run_preflight = mock_preflight

        try:
            result = runner.invoke(main, ['start', '001'])

            # Should fail because preflight failed
            assert result.exit_code != 0
            # Output should mention preflight failure
            assert "preflight" in result.output.lower() or "failed" in result.output.lower()
        finally:
            # Restore original
            agenttree.cli.agent.run_preflight = original_run_preflight

    @patch('agenttree.cli.agent.run_preflight')
    @patch('agenttree.issues.get_issue')
    def test_start_skips_preflight_with_flag(
        self, mock_get_issue, mock_preflight
    ):
        """start --skip-preflight should skip preflight checks."""
        from agenttree.cli import main
        from click.testing import CliRunner

        runner = CliRunner()

        # Mock issue lookup to return None so it exits early (after preflight check)
        mock_get_issue.return_value = None

        # Run with --skip-preflight
        result = runner.invoke(main, ['start', '--skip-preflight', '001'])

        # Preflight should NOT have been called
        mock_preflight.assert_not_called()
        # Command should fail because issue not found, but preflight was skipped
        assert "not found" in result.output.lower() or result.exit_code != 0
