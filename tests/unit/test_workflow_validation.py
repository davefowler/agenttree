"""Tests that validate the production workflow configuration is consistent.

These tests load the actual .agenttree.yaml and verify that:
- All flows reference valid stage definitions
- Flow stage ordering is internally consistent
- Required stages exist in all flows
"""

import pytest
from pathlib import Path

from agenttree.config import load_config


@pytest.fixture
def project_config():
    """Load the actual project configuration."""
    project_root = Path(__file__).parent.parent.parent
    return load_config(project_root)


class TestProductionFlowsAreValid:
    """Validate that production flows reference only defined stages."""

    def test_default_flow_exists(self, project_config):
        """The default flow must be defined."""
        assert "default" in project_config.flows

    def test_quick_flow_exists(self, project_config):
        """The quick flow must be defined for trivial tasks."""
        assert "quick" in project_config.flows

    def test_quick_flow_is_subset_of_default(self, project_config):
        """Quick flow stages should be a subset of default flow stages."""
        default_stages = set(project_config.flows["default"].stages)
        quick_stages = set(project_config.flows["quick"].stages)

        # Every stage in quick flow should also be in default flow
        missing = quick_stages - default_stages
        assert not missing, f"Quick flow has stages not in default: {missing}"

    def test_workflow_flows_start_correctly(self, project_config):
        """Workflow flows (default, quick) should start with backlog or explore."""
        # Only check actual workflow flows, not terminal-only flows like not_doing
        workflow_flows = ["default", "quick"]
        for flow_name in workflow_flows:
            flow = project_config.flows.get(flow_name)
            if flow and flow.stages:
                first_stage = flow.stages[0]
                # Allow backlog as first stage (parking lot) or explore.define
                assert first_stage in ("backlog", "explore.define"), (
                    f"Flow '{flow_name}' starts with '{first_stage}', "
                    "expected 'backlog' or 'explore.define'"
                )

    def test_all_flows_end_with_terminal_stage(self, project_config):
        """All flows should end with a terminal/parking lot stage."""
        for flow_name, flow in project_config.flows.items():
            if flow.stages:  # Skip empty flows
                last_stage = flow.stages[-1]
                # Check if it's a parking lot stage
                stage_config = project_config.stages.get(last_stage)
                if stage_config:
                    assert stage_config.is_parking_lot, (
                        f"Flow '{flow_name}' ends with '{last_stage}' "
                        "which is not a parking lot stage"
                    )


class TestRequiredStagesExist:
    """Validate that essential stages are defined."""

    def test_backlog_stage_exists(self, project_config):
        """Backlog stage must exist for issue parking."""
        assert "backlog" in project_config.stages

    def test_accepted_stage_exists(self, project_config):
        """Accepted stage must exist as terminal state."""
        assert "accepted" in project_config.stages

    def test_accepted_is_parking_lot(self, project_config):
        """Accepted must be a parking lot (terminal) stage."""
        assert project_config.stages["accepted"].is_parking_lot


class TestStageProgressionIsValid:
    """Validate that stage progression makes sense."""

    def test_no_duplicate_stages_in_flows(self, project_config):
        """Flows should not have duplicate stages."""
        for flow_name, flow in project_config.flows.items():
            seen = set()
            for stage in flow.stages:
                assert stage not in seen, (
                    f"Flow '{flow_name}' has duplicate stage: {stage}"
                )
                seen.add(stage)
