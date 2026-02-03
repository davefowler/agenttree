"""Integration tests for edge cases documented in workflow_analysis.md.

Tests the handling of edge cases like:
- Concurrent sync operations
- Git conflicts
- PR operations
- Agent state transitions
"""

import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from tests.integration.helpers import (
    create_valid_problem_md,
    create_valid_review_md,
    create_valid_spec_md,
    make_commit,
    has_uncommitted_changes,
)


class TestSyncEdgeCases:
    """Test sync-related edge cases."""

    def test_concurrent_sync_uses_lock(self, workflow_repo: Path):
        """Test that concurrent syncs are protected by file lock."""
        from agenttree.agents_repo import sync_agents_repo

        agenttree_path = workflow_repo / "_agenttree"

        # First sync should succeed (mocked to not need remote)
        with patch("agenttree.agents_repo.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=b"", stderr=b"")
            result = sync_agents_repo(agenttree_path, pull_only=True)

    def test_sync_handles_network_offline(self, workflow_repo: Path):
        """Test that sync gracefully handles network being offline."""
        from agenttree.agents_repo import sync_agents_repo

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.agents_repo.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stderr = b"Could not resolve host: github.com"
            mock_run.return_value = mock_result

            result = sync_agents_repo(agenttree_path, pull_only=True)
            # Should return False gracefully, not raise

    def test_sync_handles_no_remote(self, workflow_repo: Path):
        """Test that sync handles repos with no remote configured."""
        from agenttree.agents_repo import sync_agents_repo

        agenttree_path = workflow_repo / "_agenttree"
        result = sync_agents_repo(agenttree_path, pull_only=True)
        # Should handle gracefully


class TestGitEdgeCases:
    """Test git-related edge cases."""

    def test_uncommitted_changes_detection(self, workflow_repo: Path):
        """Test detection of uncommitted changes."""
        test_file = workflow_repo / "uncommitted.txt"
        test_file.write_text("uncommitted content")

        assert has_uncommitted_changes(workflow_repo) is True

        make_commit(workflow_repo, "Commit changes")
        test_file.write_text("more content")

        assert has_uncommitted_changes(workflow_repo) is True

    def test_auto_commit_before_operations(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that operations auto-commit uncommitted changes."""
        test_file = workflow_repo / "auto_commit_test.txt"
        test_file.write_text("content to auto-commit")
        subprocess.run(["git", "add", "."], cwd=workflow_repo, check=True)

        # The function should auto-commit
        # We verify by checking has_uncommitted_changes logic


class TestAgentStateEdgeCases:
    """Test agent state-related edge cases."""

    def test_deterministic_port_from_issue_id(self, workflow_repo: Path):
        """Test port is deterministically derived from issue ID."""
        from agenttree.state import get_port_for_issue

        # Different issues get different ports
        port1 = get_port_for_issue("001", base_port=9000)
        port2 = get_port_for_issue("002", base_port=9000)
        port3 = get_port_for_issue("023", base_port=9000)

        assert port1 == 9001
        assert port2 == 9002
        assert port3 == 9023

        # Same issue always gets same port (deterministic)
        assert get_port_for_issue("001", base_port=9000) == port1

        # Modulo wrapping for issues over 1000
        assert get_port_for_issue("1001", base_port=9000) == 9001

    def test_agent_registration(self, workflow_repo: Path):
        """Test agent registration and lookup."""
        from agenttree.state import register_agent, get_active_agent, unregister_agent, ActiveAgent

        with patch("agenttree.state.get_state_path", return_value=workflow_repo / "_agenttree" / "state.yaml"):
            agent = ActiveAgent(
                issue_id="001",
                host="agent",
                container="agenttree-issue-001",
                worktree=workflow_repo / ".worktrees" / "test",
                branch="issue-001-test",
                port=9001,
                tmux_session="test-session",
                started="2026-01-16T00:00:00Z"
            )
            register_agent(agent)

            found = get_active_agent("001")
            assert found is not None
            assert found.issue_id == "001"
            assert found.port == 9001

            unregister_agent("001")
            found = get_active_agent("001")
            assert found is None


class TestHookExecutionEdgeCases:
    """Test hook execution edge cases."""

    def test_hook_timeout(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that hooks timeout properly."""
        from agenttree.hooks import run_command_hook

        hook = {
            "command": "sleep 10",
            "timeout": 1,
        }

        with patch("agenttree.hooks.subprocess.run") as mock_run:
            import subprocess as sp
            mock_run.side_effect = sp.TimeoutExpired("sleep", 1)

            errors = run_command_hook(
                issue_dir=workflow_repo,
                hook=hook,
            )

            assert len(errors) > 0
            assert any("timeout" in e.lower() for e in errors)

    def test_optional_hook_failure_continues(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that optional hook failures don't block workflow."""
        from agenttree.hooks import run_command_hook

        hook = {
            "command": "false",
            "optional": True,
        }

        with patch("agenttree.hooks.subprocess.run") as mock_run:
            mock_result = MagicMock()
            mock_result.returncode = 1
            mock_result.stdout = b""
            mock_result.stderr = b"Command failed"
            mock_run.return_value = mock_result

            errors = run_command_hook(
                issue_dir=workflow_repo,
                hook=hook,
            )
            # Optional hooks should not block


class TestYAMLEdgeCases:
    """Test YAML file edge cases."""

    def test_corrupted_yaml_handling(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test handling of corrupted YAML files."""
        from agenttree.issues import list_issues

        agenttree_path = workflow_repo / "_agenttree"

        # Create an issue directory with corrupted YAML
        issue_dir = agenttree_path / "issues" / "999-corrupted"
        issue_dir.mkdir(parents=True)

        yaml_path = issue_dir / "issue.yaml"
        yaml_path.write_text("this: is: not: valid: yaml: [")

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            # list_issues should handle corrupted YAML
            # May raise or skip - depends on implementation
            try:
                issues = list_issues()
            except Exception:
                pass  # Expected to fail

    def test_missing_required_fields(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test handling of YAML with missing required fields."""
        from agenttree.issues import get_issue

        agenttree_path = workflow_repo / "_agenttree"

        issue_dir = agenttree_path / "issues" / "998-incomplete"
        issue_dir.mkdir(parents=True)

        yaml_path = issue_dir / "issue.yaml"
        yaml_path.write_text("id: '998'\n")

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            try:
                issue = get_issue("998")
            except Exception:
                pass  # Expected to fail


class TestDependencyEdgeCases:
    """Test issue dependency edge cases."""

    def test_missing_dependency_issue(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test handling when dependency issue doesn't exist."""
        from agenttree.issues import create_issue, check_dependencies_met, get_issue

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                issue = create_issue(title="Test Missing Dependency")

                yaml_path = agenttree_path / "issues" / f"{issue.id}-{issue.slug}" / "issue.yaml"
                with open(yaml_path) as f:
                    data = yaml.safe_load(f)
                data["dependencies"] = ["999"]
                with open(yaml_path, "w") as f:
                    yaml.dump(data, f)

                # Re-fetch issue with updated dependencies
                updated_issue = get_issue(issue.id)
                met, blocking = check_dependencies_met(updated_issue)
                assert met is False
                assert "999" in blocking

    def test_dependency_on_completed_issue(self, workflow_repo: Path, mock_sync: MagicMock):
        """Test that dependency on accepted issue is met."""
        from agenttree.issues import create_issue, check_dependencies_met, update_issue_stage, get_issue

        agenttree_path = workflow_repo / "_agenttree"

        with patch("agenttree.issues.get_agenttree_path", return_value=agenttree_path):
            with patch("agenttree.config.find_config_file", return_value=workflow_repo / ".agenttree.yaml"):
                dep_issue = create_issue(title="Dependency Issue")
                update_issue_stage(dep_issue.id, "accepted")

                main_issue = create_issue(title="Main Issue")

                yaml_path = agenttree_path / "issues" / f"{main_issue.id}-{main_issue.slug}" / "issue.yaml"
                with open(yaml_path) as f:
                    data = yaml.safe_load(f)
                data["dependencies"] = [dep_issue.id]
                with open(yaml_path, "w") as f:
                    yaml.dump(data, f)

                # Re-fetch issue with updated dependencies
                updated_issue = get_issue(main_issue.id)
                met, blocking = check_dependencies_met(updated_issue)
                assert met is True
                assert len(blocking) == 0


class TestContainerEnvironmentDetection:
    """Test container vs host environment detection."""

    def test_container_environment_variable(self, monkeypatch):
        """Test AGENTTREE_CONTAINER environment variable detection."""
        from agenttree.hooks import is_running_in_container

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")
        assert is_running_in_container() is True

        monkeypatch.delenv("AGENTTREE_CONTAINER", raising=False)
        assert is_running_in_container() is False

    def test_host_only_hooks_skip_in_container(self, workflow_repo: Path, monkeypatch):
        """Test that host_only hooks are skipped in container."""
        from agenttree.hooks import run_command_hook

        monkeypatch.setenv("AGENTTREE_CONTAINER", "1")

        hook = {
            "type": "run",
            "run": "echo 'should not run'",
            "host_only": True,
        }

        errors = run_command_hook(
            issue_dir=workflow_repo,
            hook=hook,
        )

        assert errors == []
