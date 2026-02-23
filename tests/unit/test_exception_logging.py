"""Tests for exception logging in various modules.

These tests verify that silent exception handlers now log appropriately
rather than silently swallowing errors.
"""

from unittest.mock import patch, MagicMock
import pytest


class TestContainerBareExcept:
    """Tests for container.py bare except fix."""

    def test_container_script_uses_except_exception(self) -> None:
        """Verify the embedded Python script uses 'except Exception:' not bare 'except:'."""
        from agenttree import container
        import inspect

        # Get source of the module
        source = inspect.getsource(container)

        # The script should use "except Exception:" not bare "except:"
        # Count occurrences - we should have 0 bare except: in the module
        bare_except_count = source.count("except:")
        except_exception_count = source.count("except Exception:")

        # After our fix, there should be no bare except:
        # (The except: should have been changed to except Exception:)
        assert bare_except_count == 0, (
            f"Found {bare_except_count} bare 'except:' in container.py. "
            "Should be 0 after fix."
        )
        # And at least one except Exception:
        assert except_exception_count >= 1, (
            "Expected at least one 'except Exception:' in container.py"
        )


class TestGithubLogging:
    """Tests for github.py exception logging."""

    @patch("agenttree.github.log")
    @patch("agenttree.github.gh_command")
    def test_add_label_logs_on_failure(
        self, mock_gh_command: MagicMock, mock_log: MagicMock
    ) -> None:
        """Test that add_label_to_issue logs on RuntimeError."""
        from agenttree.github import add_label_to_issue

        mock_gh_command.side_effect = RuntimeError("Label not found")

        # Should not raise
        add_label_to_issue(123, "test-label")

        # Should log debug message
        mock_log.debug.assert_called_once()
        call_args = mock_log.debug.call_args[0]
        assert "Failed to add label" in call_args[0]
        assert "test-label" in call_args

    @patch("agenttree.github.log")
    @patch("agenttree.github.gh_command")
    def test_remove_label_logs_on_failure(
        self, mock_gh_command: MagicMock, mock_log: MagicMock
    ) -> None:
        """Test that remove_label_from_issue logs on RuntimeError."""
        from agenttree.github import remove_label_from_issue

        mock_gh_command.side_effect = RuntimeError("Label not found")

        # Should not raise
        remove_label_from_issue(456, "other-label")

        # Should log debug message
        mock_log.debug.assert_called_once()
        call_args = mock_log.debug.call_args[0]
        assert "Failed to remove label" in call_args[0]
        assert "other-label" in call_args

    @patch("agenttree.github.log")
    @patch("agenttree.github.gh_command")
    def test_add_label_succeeds_without_logging(
        self, mock_gh_command: MagicMock, mock_log: MagicMock
    ) -> None:
        """Test that add_label_to_issue doesn't log on success."""
        from agenttree.github import add_label_to_issue

        mock_gh_command.return_value = None  # Success

        add_label_to_issue(123, "test-label")

        # Should not log debug
        mock_log.debug.assert_not_called()


class TestHooksLogging:
    """Tests for hooks.py exception logging."""

    @patch("agenttree.hooks.log")
    def test_pr_approval_check_logs_on_failure(self, mock_log: MagicMock) -> None:
        """Test that PR approval check logs on exception."""
        from agenttree.hooks import get_pr_approval_status

        # Mock is_pr_approved to raise
        with patch("agenttree.github.is_pr_approved") as mock_check:
            mock_check.side_effect = RuntimeError("API error")

            result = get_pr_approval_status(pr_number=123)

            # Should return False and log
            assert result is False
            mock_log.debug.assert_called_once()
            assert "PR approval check failed" in mock_log.debug.call_args[0][0]


class TestManagerHooksLogging:
    """Tests for manager_hooks.py exception logging."""

    @patch("agenttree.manager_hooks.log")
    @patch("agenttree.config.load_config")
    def test_hooks_loading_logs_on_failure(
        self, mock_load_config: MagicMock, mock_log: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Test that hook loading logs on exception."""
        from agenttree.manager_hooks import run_post_manager_hooks

        # Mock config loading to fail
        mock_load_config.side_effect = RuntimeError("Config not found")

        # Should not raise, should use defaults
        agents_dir = tmp_path  # type: ignore
        run_post_manager_hooks(agents_dir)

        # Should log debug message
        mock_log.debug.assert_called()
        assert "Failed to load manager hooks config" in mock_log.debug.call_args[0][0]
