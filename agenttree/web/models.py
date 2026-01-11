"""Pydantic models for web API."""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class StageEnum(str, Enum):
    """Kanban stages."""

    BACKLOG = "backlog"
    PROBLEM = "problem"
    PROBLEM_REVIEW = "problem_review"
    RESEARCH = "research"
    PLAN_REVIEW = "plan_review"
    IMPLEMENT = "implement"
    IMPLEMENTATION_REVIEW = "implementation_review"
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
    status: IssueStatus = IssueStatus.OPEN
    url: Optional[str] = None
    assigned_agent: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class IssueUpdate(BaseModel):
    """Issue update request."""

    stage: Optional[StageEnum] = None
    status: Optional[IssueStatus] = None
    assigned_agent: Optional[int] = None


class IssueMoveRequest(BaseModel):
    """Request to move issue to new stage."""

    stage: StageEnum


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
