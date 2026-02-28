"""Pydantic models for web API."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class IssueStatus(str, Enum):
    """Issue status."""

    OPEN = "open"
    CLOSED = "closed"


class IssueBase(BaseModel):
    """Base issue model."""

    number: int
    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)
    assignees: list[str] = Field(default_factory=list)


class Issue(IssueBase):
    """Full issue model."""

    stage: str = "backlog"  # Dot path (e.g., "explore.define", "implement.code")
    status: IssueStatus = IssueStatus.OPEN
    priority: str = "medium"
    url: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    port: int | None = None  # Dev server port for this issue
    tmux_active: bool = False
    has_worktree: bool = False
    created_at: datetime
    updated_at: datetime
    dependencies: list[int] = Field(default_factory=list)
    dependents: list[int] = Field(default_factory=list)
    processing: str | None = None  # "exit", "enter", or None
    ci_escalated: bool = False
    flow: str = "default"  # Workflow flow: "default" or "quick"
    time_in_stage: str = "0m"  # Formatted duration in current stage (e.g., "23m", "2h", "3d")

    @property
    def is_review(self) -> bool:
        """Check if issue is in a human review stage (looked up from config)."""
        from agenttree.config import load_config
        return load_config().is_human_review(self.stage)


class IssueUpdate(BaseModel):
    """Issue update request."""

    stage: str | None = None
    status: IssueStatus | None = None


class IssueMoveRequest(BaseModel):
    """Request to move issue to new stage."""

    stage: str


class PriorityUpdateRequest(BaseModel):
    """Request to update issue priority."""

    priority: str


class IssueDocumentUpdate(BaseModel):
    """Update an issue document."""

    content: str


class AgentStatus(BaseModel):
    """Agent status."""

    agent_num: int
    status: str  # idle, working, busy
    current_issue: int | None = None
    current_stage: str | None = None
    tmux_active: bool = False
    last_activity: datetime | None = None


class KanbanBoard(BaseModel):
    """Kanban board view."""

    stages: dict[str, list[Issue]]
    total_issues: int
