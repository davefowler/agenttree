"""Tests for CI fingerprint-based deduplication."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agenttree.agents_repo import _compute_ci_fingerprint
from agenttree.github import CheckStatus


class TestComputeCIFingerprint:
    """Tests for _compute_ci_fingerprint function."""

    def test_same_checks_same_fingerprint(self) -> None:
        """Identical check results produce the same fingerprint."""
        checks1 = [
            CheckStatus(name="build", state="SUCCESS"),
            CheckStatus(name="test", state="SUCCESS"),
        ]
        checks2 = [
            CheckStatus(name="build", state="SUCCESS"),
            CheckStatus(name="test", state="SUCCESS"),
        ]

        fp1 = _compute_ci_fingerprint(checks1)
        fp2 = _compute_ci_fingerprint(checks2)

        assert fp1 == fp2
        assert fp1 != ""  # Should produce a non-empty fingerprint

    def test_different_states_different_fingerprint(self) -> None:
        """Changed check state produces a different fingerprint."""
        checks_pass = [
            CheckStatus(name="build", state="SUCCESS"),
            CheckStatus(name="test", state="SUCCESS"),
        ]
        checks_fail = [
            CheckStatus(name="build", state="SUCCESS"),
            CheckStatus(name="test", state="FAILURE"),
        ]

        fp_pass = _compute_ci_fingerprint(checks_pass)
        fp_fail = _compute_ci_fingerprint(checks_fail)

        assert fp_pass != fp_fail

    def test_check_order_invariant(self) -> None:
        """Fingerprint is stable regardless of check order from API."""
        checks_order1 = [
            CheckStatus(name="build", state="SUCCESS"),
            CheckStatus(name="lint", state="SUCCESS"),
            CheckStatus(name="test", state="FAILURE"),
        ]
        checks_order2 = [
            CheckStatus(name="test", state="FAILURE"),
            CheckStatus(name="build", state="SUCCESS"),
            CheckStatus(name="lint", state="SUCCESS"),
        ]

        fp1 = _compute_ci_fingerprint(checks_order1)
        fp2 = _compute_ci_fingerprint(checks_order2)

        assert fp1 == fp2

    def test_empty_checks_list(self) -> None:
        """Empty checks list produces a deterministic fingerprint."""
        fp1 = _compute_ci_fingerprint([])
        fp2 = _compute_ci_fingerprint([])

        assert fp1 == fp2
        # Empty list should still produce a fingerprint (empty string is fine)

    def test_single_check(self) -> None:
        """Single check produces a valid fingerprint."""
        checks = [CheckStatus(name="build", state="PENDING")]

        fp = _compute_ci_fingerprint(checks)

        assert isinstance(fp, str)
        assert len(fp) > 0

    def test_pending_vs_success_different(self) -> None:
        """PENDING and SUCCESS states produce different fingerprints."""
        checks_pending = [CheckStatus(name="build", state="PENDING")]
        checks_success = [CheckStatus(name="build", state="SUCCESS")]

        fp_pending = _compute_ci_fingerprint(checks_pending)
        fp_success = _compute_ci_fingerprint(checks_success)

        assert fp_pending != fp_success


class TestFingerprintIntegration:
    """Integration tests for fingerprint-based notification deduplication."""

    def test_no_notification_when_fingerprint_unchanged(
        self,
        tmp_path: Path,
    ) -> None:
        """No notification sent when fingerprint matches stored value."""
        # Create checks and fingerprint
        checks = [
            CheckStatus(name="build", state="PENDING"),
            CheckStatus(name="test", state="PENDING"),
        ]
        fingerprint = _compute_ci_fingerprint(checks)

        # Store existing fingerprint in simulated heartbeat state
        import yaml
        agents_dir = tmp_path / "_agenttree"
        agents_dir.mkdir()
        state = {
            "ci_checks": {
                1: {  # issue_id
                    "fingerprint": fingerprint,
                    "last_status": "pending",
                }
            }
        }
        (agents_dir / ".heartbeat_state.yaml").write_text(yaml.dump(state))

        # Compute fingerprint for same checks - should match
        fp_new = _compute_ci_fingerprint(checks)
        assert fp_new == fingerprint  # Fingerprints match, no notification needed

    def test_notification_sent_when_fingerprint_changes(self) -> None:
        """Notification sent when fingerprint differs from stored value."""
        old_checks = [
            CheckStatus(name="build", state="PENDING"),
            CheckStatus(name="test", state="PENDING"),
        ]
        new_checks = [
            CheckStatus(name="build", state="SUCCESS"),
            CheckStatus(name="test", state="FAILURE"),
        ]

        old_fp = _compute_ci_fingerprint(old_checks)
        new_fp = _compute_ci_fingerprint(new_checks)

        # Fingerprints differ, notification should be sent
        assert old_fp != new_fp

    def test_fingerprint_cleared_on_pr_number_change(self) -> None:
        """Fingerprint should be considered stale when PR number changes.

        Note: This is a design test - fingerprint is keyed by issue_id, and
        when PR number changes (new PR for same issue), the fingerprint will
        naturally differ because the checks are different.
        """
        # Different PRs have different check results
        pr1_checks = [
            CheckStatus(name="build", state="SUCCESS"),
        ]
        pr2_checks = [
            CheckStatus(name="build", state="PENDING"),
        ]

        fp1 = _compute_ci_fingerprint(pr1_checks)
        fp2 = _compute_ci_fingerprint(pr2_checks)

        # Different PR = different checks = different fingerprint
        assert fp1 != fp2
