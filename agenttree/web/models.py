"""Pydantic models for web API."""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class StageEnum(str, Enum):
    """Kanban stages."""

    BACKLOG = "backlog"
    DEFINE = "define"
    RESEARCH = "research"
    PLAN = "plan"
    PLAN_ASSESS = "plan_assess"
    PLAN_REVISE = "plan_revise"
    PLAN_REVIEW = "plan_review"
    IMPLEMENT = "implement"
    INDEPENDENT_CODE_REVIEW = "independent_code_review"
    ADDRESS_INDEPENDENT_REVIEW = "address_independent_review"
    UI_REVIEW = "ui_review"
    IMPLEMENTATION_REVIEW = "implementation_review"
    KNOWLEDGE_BASE = "knowledge_base"
    ACCEPTED = "accepted"
    NOT_DOING = "not_doing"


class IssueStatus(str, Enum):
    """Issue status."""

    OPEN = "open"
    CLOSED = "closed"


class IssueBase(BaseModel):
    """Base issue model."""

    number: int
    title: str
    body: str = ""
    labels: List[str] = Field(default_factory=list)
    assignees: List[str] = Field(default_factory=list)


class Issue(IssueBase):
    """Full issue model."""

    stage: StageEnum = StageEnum.BACKLOG
    substage: Optional[str] = None
    status: IssueStatus = IssueStatus.OPEN
    priority: str = "medium"
    url: Optional[str] = None
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    port: Optional[int] = None  # Dev server port for this issue
    tmux_active: bool = False
    has_worktree: bool = False
    created_at: datetime
    updated_at: datetime
    dependencies: List[int] = Field(default_factory=list)
    dependents: List[int] = Field(default_factory=list)
    flow: str = "default"  # Workflow flow (default, quick, etc.)
    processing: Optional[str] = None  # "exit", "enter", or None (not processing)
    ci_escalated: bool = False  # CI failed too many times, escalated to human

    @property
    def is_review(self) -> bool:
        """Check if issue is in a human review stage."""
        return self.stage in (StageEnum.PLAN_REVIEW, StageEnum.IMPLEMENTATION_REVIEW, StageEnum.INDEPENDENT_CODE_REVIEW)


class IssueUpdate(BaseModel):
    """Issue update request."""

    stage: Optional[StageEnum] = None
    status: Optional[IssueStatus] = None


class IssueMoveRequest(BaseModel):
    """Request to move issue to new stage."""

    stage: StageEnum


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
    current_issue: Optional[int] = None
    current_stage: Optional[StageEnum] = None
    tmux_active: bool = False
    last_activity: Optional[datetime] = None


class KanbanBoard(BaseModel):
    """Kanban board view."""

    stages: dict[StageEnum, List[Issue]]
    total_issues: int
