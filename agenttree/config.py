"""Configuration management for AgentTree."""

from pathlib import Path
from typing import Dict, Optional, Union
import yaml
from pydantic import BaseModel, ConfigDict, Field


class ToolConfig(BaseModel):
    """Configuration for an AI tool."""

    command: str
    startup_prompt: str = "Check tasks/ folder and start working on the oldest task."
    skip_permissions: bool = False  # Add --dangerously-skip-permissions to command


class ContainerConfig(BaseModel):
    """Configuration for container settings.

    Defines how a host runs in a container (or doesn't).
    """

    enabled: bool = True  # Whether to run in a container
    image: str = "agenttree-agent:latest"  # Container image to use
    # Future: additional container options (memory limits, env vars, etc.)


class HostConfig(BaseModel):
    """Configuration for a host in the workflow.

    Hosts are execution environments that handle stages. Built-in hosts:
    - controller: Human-driven, runs on host machine (no container)
    - agent: Default AI agent, runs in container

    Custom hosts can be defined for specialized agents (e.g., code review).
    """

    name: str  # Host name (e.g., "controller", "agent", "review")
    description: str = ""  # Human-readable description

    # Container configuration (None = no container, runs on host)
    container: Optional[ContainerConfig] = None

    # AI agent settings (only for agent hosts, not controller)
    tool: Optional[str] = None  # AI tool to use (e.g., "claude", "codex")
    model: Optional[str] = None  # Model to use (e.g., "opus", "gpt-5.2")
    skill: Optional[str] = None  # Skill file path for custom agents

    # Process to run (for controller, this could be "agenttree watch")
    process: Optional[str] = None

    def is_containerized(self) -> bool:
        """Check if this host runs in a container."""
        return self.container is not None and self.container.enabled

    def is_agent(self) -> bool:
        """Check if this host is an AI agent (has tool configured)."""
        return self.tool is not None


class HooksConfig(BaseModel):
    """Configuration for host action hooks."""

    post_pr_create: list[dict] = Field(default_factory=list)  # After PR created
    post_merge: list[dict] = Field(default_factory=list)  # After merge
    post_accepted: list[dict] = Field(default_factory=list)  # After issue accepted


class SubstageConfig(BaseModel):
    """Configuration for a workflow substage."""

    name: str
    output: Optional[str] = None  # Document created by this substage
    output_optional: bool = False  # If True, missing output file doesn't error
    skill: Optional[str] = None   # Override skill file path
    model: Optional[str] = None   # Model to use for this substage (overrides stage model)
    validators: list[str] = Field(default_factory=list)  # Legacy format
    pre_completion: list[dict] = Field(default_factory=list)  # Hooks before completing
    post_start: list[dict] = Field(default_factory=list)  # Hooks after starting


class StageConfig(BaseModel):
    """Configuration for a workflow stage."""

    name: str
    output: Optional[str] = None  # Document created by this stage
    output_optional: bool = False  # If True, missing output file doesn't error
    skill: Optional[str] = None   # Override skill file path
    model: Optional[str] = None   # Model to use for this stage (overrides default_model)
    human_review: bool = False    # Requires human approval to exit
    terminal: bool = False        # Cannot progress from here (accepted, not_doing)
    redirect_only: bool = False   # Only reachable via StageRedirect, skipped in normal progression
    host: str = "agent"           # Who executes this stage: "agent" (in container) or "controller" (host)
    substages: Dict[str, SubstageConfig] = Field(default_factory=dict)
    pre_completion: list[dict] = Field(default_factory=list)  # Stage-level hooks before completing
    post_start: list[dict] = Field(default_factory=list)  # Stage-level hooks after starting

    def substage_order(self) -> list[str]:
        """Get ordered list of substage names."""
        return list(self.substages.keys())

    def get_substage(self, name: str) -> Optional[SubstageConfig]:
        """Get a substage by name."""
        return self.substages.get(name)

    def hooks_for(self, substage: Optional[str], event: str) -> list[dict]:
        """Get hooks for a substage or stage.

        Args:
            substage: Substage name, or None for stage-level hooks
            event: "pre_completion" or "post_start"

        Returns:
            List of hook configurations
        """
        if substage:
            substage_config = self.get_substage(substage)
            if substage_config:
                return getattr(substage_config, event, [])
            return []
        return getattr(self, event, [])


class ControllerConfig(BaseModel):
    """Configuration for the controller agent's stall monitoring.

    These settings control how the controller detects and handles stalled agents.
    """

    stall_threshold_min: int = 20  # Minutes before agent considered stalled
    nudge_cooldown_min: int = 30  # Minutes between nudges for same agent
    max_nudges_before_escalate: int = 3  # Escalate after N failed nudges


class SecurityConfig(BaseModel):
    """Security configuration for agents.

    NOTE: Containers are MANDATORY. There is no option to disable them.
    This config exists for future security settings, not to bypass containers.
    """

    # Reserved for future security settings
    # Containers are always required - this is not configurable


class Config(BaseModel):
    """AgentTree configuration."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    project: str = "myapp"
    worktrees_dir: Path = Field(default_factory=lambda: Path(".worktrees"))
    scripts_dir: Path = Field(default_factory=lambda: Path("scripts"))
    port_range: str = "9001-9099"
    default_tool: str = "claude"
    default_model: str = "opus"  # Model to use for Claude CLI (opus, sonnet)
    refresh_interval: int = 10
    tools: Dict[str, ToolConfig] = Field(default_factory=dict)
    hosts: Dict[str, HostConfig] = Field(default_factory=dict)  # Host configurations
    commands: Dict[str, Union[str, list[str]]] = Field(default_factory=dict)  # Named shell commands
    stages: list[StageConfig] = Field(default_factory=list)  # Must be defined in .agenttree.yaml
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    merge_strategy: str = "squash"  # squash, merge, or rebase
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    save_tmux_history: bool = False  # Save tmux session history on stage transitions
    controller: ControllerConfig = Field(default_factory=ControllerConfig)
    show_issue_yaml: bool = True  # Show issue.yaml in web UI file tabs

    def get_port_for_agent(self, agent_num: int) -> int:
        """Get port number for a specific agent.

        Args:
            agent_num: Agent number (1-based)

        Returns:
            Port number for the agent

        Raises:
            ValueError: If agent number exceeds port range
        """
        start_port, end_port = map(int, self.port_range.split("-"))
        port = start_port + (agent_num - 1)

        if port > end_port:
            raise ValueError(
                f"Agent number {agent_num} exceeds port range {self.port_range}"
            )

        return port

    def get_port_for_issue(self, issue_id: str) -> Optional[int]:
        """Get port number for a specific issue.

        Port is calculated from issue ID using the configured port_range.
        Returns None if issue_id is not a valid integer or if the port
        would exceed the configured range.

        Args:
            issue_id: Issue ID (string, typically numeric like "001", "042")

        Returns:
            Port number, or None if issue_id is invalid or exceeds range
        """
        try:
            issue_num = int(issue_id)
            return self.get_port_for_agent(issue_num)
        except (ValueError, TypeError):
            return None

    def get_worktree_path(self, agent_num: int) -> Path:
        """Get worktree path for a specific agent (legacy numbered agents).

        Args:
            agent_num: Agent number

        Returns:
            Path to the agent's worktree
        """
        expanded_dir = Path(self.worktrees_dir).expanduser()
        return expanded_dir / f"{self.project}-agent-{agent_num}"

    def get_issue_worktree_path(self, issue_id: str, slug: str) -> Path:
        """Get worktree path for an issue-bound agent.

        Args:
            issue_id: Issue ID (e.g., "023")
            slug: Issue slug (e.g., "fix-login-bug")

        Returns:
            Path to the issue's worktree
        """
        expanded_dir = Path(self.worktrees_dir).expanduser()
        short_slug = slug[:30] if len(slug) > 30 else slug
        return expanded_dir / f"issue-{issue_id}-{short_slug}"

    def get_tmux_session_name(self, agent_num: int) -> str:
        """Get tmux session name for a specific agent (legacy numbered agents).

        Args:
            agent_num: Agent number

        Returns:
            Tmux session name
        """
        # Standardized on -issue- naming pattern
        return f"{self.project}-issue-{agent_num}"

    def get_issue_tmux_session(self, issue_id: str) -> str:
        """Get tmux session name for an issue-bound agent.

        Args:
            issue_id: Issue ID

        Returns:
            Tmux session name
        """
        return f"{self.project}-issue-{issue_id}"

    def get_issue_container_name(self, issue_id: str) -> str:
        """Get container name for an issue-bound agent.

        Args:
            issue_id: Issue ID

        Returns:
            Container name
        """
        return f"{self.project}-issue-{issue_id}"

    def get_tool_config(self, tool_name: str) -> ToolConfig:
        """Get configuration for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Tool configuration (creates default if not found)
        """
        if tool_name in self.tools:
            return self.tools[tool_name]

        # Return default config for unknown tools
        return ToolConfig(command=tool_name)

    def get_ci_script(self, script_name: str = "ci.sh") -> Path:
        """Get path to a CI script.

        Args:
            script_name: Name of the script (ci.sh, quick_ci.sh, extensive_ci.sh)

        Returns:
            Path to the script
        """
        return self.scripts_dir / script_name

    def get_stage(self, stage_name: str) -> Optional[StageConfig]:
        """Get configuration for a stage.

        Args:
            stage_name: Name of the stage

        Returns:
            Stage configuration, or None if not found
        """
        for stage in self.stages:
            if stage.name == stage_name:
                return stage
        return None

    def get_stage_names(self) -> list[str]:
        """Get list of all stage names in order.

        Returns:
            List of stage names
        """
        return [stage.name for stage in self.stages]

    def get_human_review_stages(self) -> list[str]:
        """Get list of stages that require human review.

        Returns:
            List of stage names that require human review
        """
        return [stage.name for stage in self.stages if stage.human_review]

    def get_controller_stages(self) -> list[str]:
        """Get list of stages executed by the controller (host), not agent.

        Returns:
            List of stage names where host=controller
        """
        return [stage.name for stage in self.stages if stage.host == "controller"]

    def get_all_hosts(self) -> Dict[str, HostConfig]:
        """Get all hosts including built-in defaults.

        Returns dict with:
        - Built-in 'controller' host (no container)
        - Built-in 'agent' host (containerized, uses default tool/model)
        - Any custom hosts from config

        Returns:
            Dict of host name -> HostConfig
        """
        # Start with built-in defaults
        all_hosts: Dict[str, HostConfig] = {
            "controller": HostConfig(
                name="controller",
                description="Human-driven controller (runs on host)",
                container=None,  # No container
                process=None,  # Could be "agenttree watch" in future
            ),
            "agent": HostConfig(
                name="agent",
                description="Default AI agent",
                container=ContainerConfig(enabled=True),
                tool=self.default_tool,
                model=self.default_model,
            ),
        }

        # Merge in hosts from config (can override defaults)
        all_hosts.update(self.hosts)

        return all_hosts

    def get_host(self, host_name: str) -> Optional[HostConfig]:
        """Get configuration for a host (including built-in defaults).

        Args:
            host_name: Name of the host

        Returns:
            HostConfig or None if not found
        """
        return self.get_all_hosts().get(host_name)

    def get_custom_agent_stages(self) -> list[str]:
        """Get list of stages that use custom agent hosts.

        Custom agent stages have a host value that is neither "agent" nor "controller"
        and exists in the hosts configuration.

        Returns:
            List of stage names where host is a custom agent
        """
        all_hosts = self.get_all_hosts()
        return [
            stage.name for stage in self.stages
            if stage.host not in ("agent", "controller") and stage.host in all_hosts
        ]

    def get_agent_host(self, host_name: str) -> Optional[HostConfig]:
        """Get configuration for a custom agent host.

        Args:
            host_name: Name of the agent host

        Returns:
            HostConfig or None if not found
        """
        return self.hosts.get(host_name)

    def is_custom_agent_host(self, host_name: str) -> bool:
        """Check if a host name is a custom agent host (not controller or default agent).

        Args:
            host_name: Name to check

        Returns:
            True if it's a custom agent host, False otherwise
        """
        if host_name in ("controller", "agent"):
            return False
        return host_name in self.hosts

    def get_non_agent_stages(self) -> list[str]:
        """Get list of stages NOT executed by the default agent.

        This includes controller stages and custom agent stages.
        Used to determine which stages the default agent should block on.

        Returns:
            List of stage names where host != "agent"
        """
        return [stage.name for stage in self.stages if stage.host != "agent"]

    def host_is_containerized(self, host_name: str) -> bool:
        """Check if a host runs in a container.

        Args:
            host_name: Name of the host

        Returns:
            True if containerized, False otherwise
        """
        host = self.get_host(host_name)
        if host:
            return host.is_containerized()
        # Default: assume custom hosts are containerized
        return host_name != "controller"

    def substages_for(self, stage_name: str) -> list[str]:
        """Get ordered list of substage names for a stage.

        Args:
            stage_name: Name of the stage

        Returns:
            List of substage names (empty if no substages)
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return []
        return stage.substage_order()

    def skill_path(self, stage_name: str, substage: Optional[str] = None) -> str:
        """Get the skill file path for a stage/substage.

        Convention: skills/{stage}.md or skills/{stage}/{substage}.md
        Can be overridden with explicit skill property in config.

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            Relative path to skill file (from _agenttree/)
        """
        stage = self.get_stage(stage_name)

        # Check for explicit override
        if substage and stage:
            substage_config = stage.get_substage(substage)
            if substage_config and substage_config.skill:
                return f"skills/{substage_config.skill}"
        if stage and stage.skill:
            return f"skills/{stage.skill}"

        # Use convention: skills/{stage}/{substage}.md or skills/{stage}.md
        if substage:
            return f"skills/{stage_name}/{substage}.md"
        return f"skills/{stage_name}.md"

    def output_for(self, stage_name: str, substage: Optional[str] = None) -> Optional[str]:
        """Get the output document name for a stage/substage.

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            Document name (e.g., "problem.md") or None
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return None

        # Check substage output first
        if substage:
            substage_config = stage.get_substage(substage)
            if substage_config and substage_config.output:
                return substage_config.output

        # Fall back to stage output
        return stage.output

    def model_for(self, stage_name: str, substage: Optional[str] = None) -> str:
        """Get the model to use for a stage/substage.

        Resolution order:
        1. Substage model (if substage specified and has model)
        2. Stage model (if stage has model)
        3. default_model (fallback)

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            Model name (e.g., "opus", "haiku", "sonnet")
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return self.default_model

        # Check substage model first
        if substage:
            substage_config = stage.get_substage(substage)
            if substage_config and substage_config.model:
                return substage_config.model

        # Check stage model
        if stage.model:
            return stage.model

        # Fall back to default model
        return self.default_model

    def validators_for(self, stage_name: str, substage: Optional[str] = None) -> list[str]:
        """Get validators for a stage/substage.

        Args:
            stage_name: Name of the stage
            substage: Optional substage name

        Returns:
            List of validator names
        """
        stage = self.get_stage(stage_name)
        if stage is None:
            return []

        if substage:
            substage_config = stage.get_substage(substage)
            if substage_config:
                return substage_config.validators

        return []

    def is_terminal(self, stage_name: str) -> bool:
        """Check if a stage is terminal (cannot progress further).

        Args:
            stage_name: Name of the stage

        Returns:
            True if terminal, False otherwise
        """
        stage = self.get_stage(stage_name)
        return stage.terminal if stage else False

    def get_next_stage(
        self,
        current_stage: str,
        current_substage: Optional[str] = None,
    ) -> tuple[str, Optional[str], bool]:
        """Calculate the next stage/substage.

        Args:
            current_stage: Current stage name
            current_substage: Current substage (if any)

        Returns:
            Tuple of (next_stage, next_substage, is_human_review)
        """
        stage_config = self.get_stage(current_stage)
        # Terminal stages don't progress further
        if stage_config is None or stage_config.terminal:
            return current_stage, current_substage, False

        substages = stage_config.substage_order()

        # If we have substages, try to advance within them
        if substages and current_substage:
            try:
                idx = substages.index(current_substage)
                if idx < len(substages) - 1:
                    # Move to next substage
                    return current_stage, substages[idx + 1], False
            except ValueError:
                pass  # substage not found, move to next stage

        # Move to next stage (skip redirect_only stages)
        stage_names = self.get_stage_names()
        try:
            stage_idx = stage_names.index(current_stage)
            # Look for next non-redirect_only stage
            for next_idx in range(stage_idx + 1, len(stage_names)):
                next_stage_name = stage_names[next_idx]
                next_stage = self.get_stage(next_stage_name)
                if next_stage:
                    # Skip redirect_only stages in normal progression
                    if next_stage.redirect_only:
                        continue
                    next_substages = next_stage.substage_order()
                    next_substage = next_substages[0] if next_substages else None
                    return next_stage_name, next_substage, next_stage.human_review
        except ValueError:
            pass

        # Already at end
        return current_stage, current_substage, False

    def format_stage(self, stage: str, substage: Optional[str] = None) -> str:
        """Format stage/substage as a display string.

        Args:
            stage: Stage name
            substage: Optional substage name

        Returns:
            Formatted string like "implement/code_review" or "backlog"
        """
        if substage:
            return f"{stage}/{substage}"
        return stage

    def parse_stage(self, stage_str: str) -> tuple[str, Optional[str]]:
        """Parse a stage string into stage and substage.

        Args:
            stage_str: String like "implement/code_review" or "backlog"

        Returns:
            Tuple of (stage, substage) where substage may be None
        """
        if "/" in stage_str:
            parts = stage_str.split("/", 1)
            return parts[0], parts[1]
        return stage_str, None


def find_config_file(start_path: Path) -> Optional[Path]:
    """Find .agenttree.yaml file by walking up directory tree.

    Args:
        start_path: Directory to start searching from

    Returns:
        Path to config file, or None if not found
    """
    current = start_path.resolve()

    # Walk up the directory tree
    while True:
        config_file = current / ".agenttree.yaml"
        if config_file.exists():
            return config_file

        # Check if we've reached the root
        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from .agenttree.yaml file.

    Args:
        path: Path to directory containing config file (default: current directory)

    Returns:
        Loaded configuration (or default if file not found)
    """
    if path is None:
        path = Path.cwd()

    config_file = find_config_file(path)

    if config_file is None:
        return Config()

    with open(config_file, "r") as f:
        data = yaml.safe_load(f)

    if data is None:
        return Config()

    # Auto-populate 'name' field for substages from the key
    if "stages" in data:
        for stage in data["stages"]:
            if "substages" in stage and isinstance(stage["substages"], dict):
                for substage_name, substage_config in stage["substages"].items():
                    if substage_config is None:
                        stage["substages"][substage_name] = {"name": substage_name}
                    elif "name" not in substage_config:
                        substage_config["name"] = substage_name

    # Auto-populate 'name' field for hosts from the key
    if "hosts" in data and isinstance(data["hosts"], dict):
        for host_name, host_config in data["hosts"].items():
            if host_config is None:
                data["hosts"][host_name] = {"name": host_name}
            elif isinstance(host_config, dict):
                if "name" not in host_config:
                    host_config["name"] = host_name
                # Ensure container config is properly structured
                if "container" in host_config and host_config["container"] is True:
                    host_config["container"] = {"enabled": True}
                elif "container" in host_config and host_config["container"] is False:
                    host_config["container"] = None

    return Config(**data)
