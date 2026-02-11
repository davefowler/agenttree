"""Tests for workflow flows feature."""

import pytest
import tempfile
from pathlib import Path

import yaml

from agenttree.config import Config, FlowConfig, StageConfig, SubstageConfig, load_config
from agenttree.issues import Issue, create_issue, Priority


class TestFlowConfig:
    """Tests for FlowConfig model."""

    def test_flow_config_creation(self):
        """Test creating a FlowConfig."""
        flow = FlowConfig(name="quick", stages=["explore.define", "implement.code", "accepted"])
        assert flow.name == "quick"
        assert flow.stages == ["explore.define", "implement.code", "accepted"]

    def test_flow_config_empty_stages(self):
        """Test FlowConfig with empty stages list."""
        flow = FlowConfig(name="empty", stages=[])
        assert flow.stages == []


class TestConfigFlows:
    """Tests for Config with flows."""

    def test_config_flows_field(self):
        """Test Config has flows field."""
        config = Config()
        assert hasattr(config, "flows")
        assert config.flows == {}

    def test_config_default_flow_field(self):
        """Test Config has default_flow field."""
        config = Config()
        assert hasattr(config, "default_flow")
        assert config.default_flow == "default"

    def test_get_flow(self):
        """Test get_flow method."""
        flow = FlowConfig(name="quick", stages=["explore.define", "implement.code"])
        config = Config(flows={"quick": flow})

        assert config.get_flow("quick") == flow
        assert config.get_flow("nonexistent") is None

    def test_get_flow_stage_names(self):
        """Test get_flow_stage_names returns correct stages."""
        flow = FlowConfig(name="quick", stages=["explore.define", "implement.code", "accepted"])
        config = Config(flows={"quick": flow})

        assert config.get_flow_stage_names("quick") == ["explore.define", "implement.code", "accepted"]

    def test_get_flow_stage_names_nonexistent(self):
        """Test get_flow_stage_names for nonexistent flow."""
        config = Config()
        assert config.get_flow_stage_names("nonexistent") == []

    def test_get_flow_stage_names_default_fallback(self):
        """Test get_flow_stage_names falls back to stages dict for default.

        When Config is created directly without flows (e.g., in tests or legacy configs),
        requesting the "default" flow falls back to using all stages in definition order.
        """
        stages = {
            "backlog": StageConfig(name="backlog"),
            "explore.define": StageConfig(name="explore.define"),
            "accepted": StageConfig(name="accepted", is_parking_lot=True),
        }
        config = Config(stages=stages)  # No flows defined

        # Falls back to stages dict keys for "default" flow when no flows defined
        assert config.get_flow_stage_names("default") == ["backlog", "explore.define", "accepted"]


class TestGetNextStageWithFlows:
    """Tests for get_next_stage with flow parameter."""

    def test_get_next_stage_default_flow(self):
        """Test get_next_stage uses default flow."""
        from agenttree.config import SubstageConfig
        stages = {
            "explore": StageConfig(name="explore", substages={
                "define": SubstageConfig(name="define"),
                "research": SubstageConfig(name="research"),
            }),
            "plan": StageConfig(name="plan", substages={
                "draft": SubstageConfig(name="draft"),
            }),
            "accepted": StageConfig(name="accepted", is_parking_lot=True),
        }
        default_flow = FlowConfig(name="default", stages=["explore.define", "explore.research", "plan.draft", "accepted"])
        config = Config(stages=stages, flows={"default": default_flow})

        next_stage, _ = config.get_next_stage("explore.define", flow="default")
        assert next_stage == "explore.research"

    def test_get_next_stage_quick_flow(self):
        """Test get_next_stage uses quick flow that skips stages."""
        from agenttree.config import SubstageConfig
        stages = {
            "explore": StageConfig(name="explore", substages={
                "define": SubstageConfig(name="define"),
                "research": SubstageConfig(name="research"),
            }),
            "plan": StageConfig(name="plan", substages={
                "draft": SubstageConfig(name="draft"),
            }),
            "implement": StageConfig(name="implement", substages={
                "code": SubstageConfig(name="code"),
            }),
            "accepted": StageConfig(name="accepted", is_parking_lot=True),
        }
        default_flow = FlowConfig(name="default", stages=["explore.define", "explore.research", "plan.draft", "implement.code", "accepted"])
        quick_flow = FlowConfig(name="quick", stages=["explore.define", "implement.code", "accepted"])
        config = Config(stages=stages, flows={"default": default_flow, "quick": quick_flow})

        # Default flow: explore.define -> explore.research
        next_stage, _ = config.get_next_stage("explore.define", flow="default")
        assert next_stage == "explore.research"

        # Quick flow: explore.define -> implement.code (skips research and plan)
        next_stage, _ = config.get_next_stage("explore.define", flow="quick")
        assert next_stage == "implement.code"

    def test_get_next_stage_terminal_stage(self):
        """Test get_next_stage stays at terminal stage."""
        stages = {
            "explore": StageConfig(name="explore", substages={
                "define": SubstageConfig(name="define"),
            }),
            "accepted": StageConfig(name="accepted", is_parking_lot=True),
        }
        flow = FlowConfig(name="default", stages=["explore.define", "accepted"])
        config = Config(stages=stages, flows={"default": flow})

        next_stage, _ = config.get_next_stage("accepted", flow="default")
        assert next_stage == "accepted"

    def test_get_next_stage_advances_through_flow(self):
        """Test get_next_stage advances through dot-path stages in a flow."""
        from agenttree.config import SubstageConfig
        stages = {
            "explore": StageConfig(name="explore", substages={
                "define": SubstageConfig(name="define"),
                "research": SubstageConfig(name="research"),
            }),
            "implement": StageConfig(name="implement", substages={
                "code": SubstageConfig(name="code"),
            }),
        }
        flow = FlowConfig(name="default", stages=["explore.define", "explore.research", "implement.code"])
        config = Config(stages=stages, flows={"default": flow})

        # Should advance to next stage in flow
        next_stage, _ = config.get_next_stage("explore.define", flow="default")
        assert next_stage == "explore.research"

        # Then advance to next stage
        next_stage, _ = config.get_next_stage("explore.research", flow="default")
        assert next_stage == "implement.code"


class TestLoadConfigWithFlows:
    """Tests for load_config with flows."""

    def test_load_config_with_flows_section(self, tmp_path):
        """Test loading config with flows section."""
        config_content = """
flows:
  default:
    stages:
      backlog:
      define:
      implement:
      accepted:
        is_parking_lot: true
  quick:
    stages: [backlog, define, accepted]

default_flow: default
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        config = load_config(tmp_path)

        assert "default" in config.flows
        assert "quick" in config.flows
        assert config.flows["default"].stages == ["backlog", "define", "implement", "accepted"]
        assert config.flows["quick"].stages == ["backlog", "define", "accepted"]
        assert config.default_flow == "default"

    def test_load_config_implicit_default_flow(self, tmp_path):
        """Test load_config creates implicit default flow when none defined."""
        config_content = """
flows:
  default:
    stages:
      backlog:
      define:
      accepted:
        is_parking_lot: true
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        config = load_config(tmp_path)

        assert "default" in config.flows
        assert config.flows["default"].stages == ["backlog", "define", "accepted"]

    def test_load_config_invalid_flow_reference(self, tmp_path):
        """Test load_config raises error for invalid stage reference in flow."""
        config_content = """
flows:
  default:
    stages:
      define:
      accepted:
        is_parking_lot: true
  broken:
    stages: [define, nonexistent, accepted]
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        with pytest.raises(ValueError) as exc_info:
            load_config(tmp_path)

        assert "references unknown" in str(exc_info.value)
        assert "nonexistent" in str(exc_info.value)

    def test_load_config_empty_flow_stages(self, tmp_path):
        """Test load_config handles flow with empty stages list."""
        config_content = """
flows:
  default:
    stages:
      define:
      accepted:
        is_parking_lot: true
  empty:
    stages: []
"""
        config_file = tmp_path / ".agenttree.yaml"
        config_file.write_text(config_content)

        config = load_config(tmp_path)
        # Empty flow should have empty stages list
        assert config.flows["empty"].stages == []


class TestIssueFlowField:
    """Tests for Issue.flow field."""

    def test_issue_has_flow_field(self):
        """Test Issue model has flow field."""
        issue = Issue(
            id="001",
            slug="test",
            title="Test Issue",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
        )
        assert hasattr(issue, "flow")
        assert issue.flow == "default"

    def test_issue_flow_field_custom(self):
        """Test Issue flow field can be set."""
        issue = Issue(
            id="001",
            slug="test",
            title="Test Issue",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
            flow="quick",
        )
        assert issue.flow == "quick"

    def test_issue_flow_serialization(self):
        """Test Issue flow field is serialized correctly."""
        issue = Issue(
            id="001",
            slug="test",
            title="Test Issue",
            created="2024-01-01T00:00:00Z",
            updated="2024-01-01T00:00:00Z",
            flow="quick",
        )
        data = issue.model_dump()
        assert data["flow"] == "quick"


class TestCreateIssueWithFlow:
    """Tests for create_issue with flow parameter."""

    def test_create_issue_default_flow(self, tmp_path, monkeypatch):
        """Test create_issue uses default flow."""
        # Set up mock _agenttree directory
        agenttree_dir = tmp_path / "_agenttree"
        agenttree_dir.mkdir()
        (agenttree_dir / "issues").mkdir()

        monkeypatch.setattr("agenttree.issues.get_agenttree_path", lambda: agenttree_dir)
        monkeypatch.setattr("agenttree.issues.sync_agents_repo", lambda *args, **kwargs: None)

        issue = create_issue(title="Test Issue")
        assert issue.flow == "default"

    def test_create_issue_custom_flow(self, tmp_path, monkeypatch):
        """Test create_issue with custom flow."""
        # Set up mock _agenttree directory
        agenttree_dir = tmp_path / "_agenttree"
        agenttree_dir.mkdir()
        (agenttree_dir / "issues").mkdir()

        monkeypatch.setattr("agenttree.issues.get_agenttree_path", lambda: agenttree_dir)
        monkeypatch.setattr("agenttree.issues.sync_agents_repo", lambda *args, **kwargs: None)

        issue = create_issue(title="Test Issue", flow="quick")
        assert issue.flow == "quick"

    def test_create_issue_flow_persisted(self, tmp_path, monkeypatch):
        """Test create_issue persists flow in issue.yaml."""
        # Set up mock _agenttree directory
        agenttree_dir = tmp_path / "_agenttree"
        agenttree_dir.mkdir()
        (agenttree_dir / "issues").mkdir()

        monkeypatch.setattr("agenttree.issues.get_agenttree_path", lambda: agenttree_dir)
        monkeypatch.setattr("agenttree.issues.sync_agents_repo", lambda *args, **kwargs: None)

        issue = create_issue(title="Test Issue", flow="quick")

        # Read the issue.yaml file
        issue_dir = agenttree_dir / "issues" / f"{issue.id}-{issue.slug}"
        yaml_file = issue_dir / "issue.yaml"
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        assert data["flow"] == "quick"
