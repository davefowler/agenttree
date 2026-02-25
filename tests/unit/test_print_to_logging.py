"""Tests for print-to-logging/console conversions.

Verifies that modules use proper logging and Rich console
instead of raw print() for output.
"""

import logging
import pytest


class TestContainerHealthCheck:
    """Test that container.py health check uses raw print (intentionally)."""

    def test_health_check_script_contains_raw_print(self) -> None:
        """The health check script must use raw print('OK') for protocol."""
        from agenttree import container

        # Read the module source and verify the health check script
        import inspect

        source = inspect.getsource(container)
        # The script template should contain print("OK") for protocol
        assert 'print("OK")' in source


class TestIssuesLogging:
    """Test that issues.py uses logging for warnings."""

    def test_module_has_logger(self) -> None:
        """issues module should have a logger."""
        from agenttree import issues

        assert hasattr(issues, "log")
        assert isinstance(issues.log, logging.Logger)
        assert issues.log.name == "agenttree.issues"


class TestTmuxLogging:
    """Test that tmux.py uses logging for warnings."""

    def test_module_has_logger(self) -> None:
        """Tmux module should have a logger configured."""
        from agenttree import tmux

        assert hasattr(tmux, "log")
        assert isinstance(tmux.log, logging.Logger)
        assert tmux.log.name == "agenttree.tmux"


class TestCliIssuesRawPrint:
    """Test that cli/issues.py keeps raw print for scripting."""

    def test_json_output_is_raw(self) -> None:
        """JSON output should use raw print without Rich formatting."""
        # Read the source to verify raw print is used (not console.print)
        from agenttree.cli import issues

        import inspect

        source = inspect.getsource(issues)

        # The get command should have raw print for --json output
        # Look for the scripting comment and print statements
        assert "Print raw value for scripting" in source
        assert "print(json.dumps(" in source


class TestWebAppLogging:
    """Test that web/app.py uses proper logging and console."""

    def test_module_has_console(self) -> None:
        """Web app module should have Rich console configured."""
        pytest.importorskip("fastapi")
        from agenttree.web import app

        assert hasattr(app, "console")
        # Console is from rich.console
        assert app.console.__class__.__name__ == "Console"

    def test_module_has_logger(self) -> None:
        """Web app module should have a logger configured."""
        pytest.importorskip("fastapi")
        from agenttree.web import app

        assert hasattr(app, "logger")
        assert isinstance(app.logger, logging.Logger)
        assert app.logger.name == "agenttree.web"


class TestModulesHaveProperOutputMechanisms:
    """Test that all modified modules have proper console/logger imports."""

    def test_agents_repo_has_console(self) -> None:
        """agents_repo should have Rich console."""
        from agenttree import agents_repo

        assert hasattr(agents_repo, "console")
        assert agents_repo.console.__class__.__name__ == "Console"

    def test_agents_repo_has_logger(self) -> None:
        """agents_repo should have a logger."""
        from agenttree import agents_repo

        assert hasattr(agents_repo, "log")
        assert isinstance(agents_repo.log, logging.Logger)
        assert agents_repo.log.name == "agenttree.agents_repo"

    def test_container_has_console(self) -> None:
        """container should have Rich console."""
        from agenttree import container

        assert hasattr(container, "console")
        assert container.console.__class__.__name__ == "Console"

    def test_container_has_logger(self) -> None:
        """container should have a logger."""
        from agenttree import container

        assert hasattr(container, "log")
        assert isinstance(container.log, logging.Logger)
        assert container.log.name == "agenttree.container"

    def test_issues_has_logger(self) -> None:
        """issues should have a logger."""
        from agenttree import issues

        assert hasattr(issues, "log")
        assert isinstance(issues.log, logging.Logger)


class TestNoRemainingRawPrintsInConvertedFiles:
    """Verify that converted files no longer have raw print() calls (except intentional ones)."""

    @pytest.mark.parametrize("module_name", ["agents_repo", "issues", "tmux"])
    def test_no_raw_prints(self, module_name: str) -> None:
        """Converted modules should not have raw print() calls."""
        import inspect
        import importlib
        import re

        module = importlib.import_module(f"agenttree.{module_name}")
        source = inspect.getsource(module)
        # Match standalone print( at start of line (not console.print)
        prints = re.findall(r'^\s*print\(', source, re.MULTILINE)
        assert len(prints) == 0, f"Found {len(prints)} raw print() calls in {module_name}.py"

    def test_container_only_health_check_print(self) -> None:
        """container.py should only have the health check print('OK')."""
        import inspect
        import re
        from agenttree import container

        source = inspect.getsource(container)
        # Match standalone print( at start of line (not console.print)
        prints = re.findall(r'^\s*print\(', source, re.MULTILINE)
        # Should only find print("OK") in the health check script
        assert len(prints) == 1, f"Expected 1 print (health check), found {len(prints)}"
        assert 'print("OK")' in source
