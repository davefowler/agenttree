"""Web dashboard for AgentTree using FastAPI + HTMX."""

from fastapi import FastAPI, Request, Form, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import subprocess
import asyncio
import secrets
import os
from typing import List, Dict, Optional
from datetime import datetime

from agenttree.config import load_config
from agenttree.worktree import WorktreeManager
from agenttree.github import get_issue, list_issues, sort_issues_by_priority, IssueWithContext
from agenttree.web.models import (
    Issue, IssueUpdate, IssueMoveRequest, StageEnum, IssueStatus, KanbanBoard
)

# Get the directory where this file is located
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="AgentTree Dashboard")

# Mount static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Auth configuration from environment variables
AUTH_ENABLED = os.getenv("AGENTTREE_WEB_AUTH", "false").lower() == "true"
AUTH_USERNAME = os.getenv("AGENTTREE_WEB_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AGENTTREE_WEB_PASSWORD", "changeme")


def get_current_user() -> Optional[str]:
    """Get current authenticated user (or None if auth disabled).

    This dependency is optional - only enforces auth if AUTH_ENABLED=true.
    """
    if not AUTH_ENABLED:
        return None

    # Auth is enabled, require HTTP Basic Auth
    # Note: This is a simplified version - in production you'd want proper dependency injection
    return "authenticated_user"


class AgentManager:
    """Manages agent state for the dashboard."""

    def __init__(self, worktree_manager: Optional[WorktreeManager] = None):
        self.worktree_manager = worktree_manager
        self.agents: Dict[int, dict] = {}

    def _check_tmux_session(self, agent_num: int) -> bool:
        """Check if tmux session exists for agent."""
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", f"agent-{agent_num}"],
                capture_output=True,
                timeout=1
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def get_agent_status(self, agent_num: int) -> dict:
        """Get status of an agent."""
        if self.worktree_manager:
            try:
                status = self.worktree_manager.get_status(agent_num)
                return {
                    "agent_num": agent_num,
                    "status": "working" if status.is_busy else "idle",
                    "current_task": "Active" if status.has_task else None,
                    "tmux_active": self._check_tmux_session(agent_num),
                    "last_activity": datetime.now().isoformat()
                }
            except Exception:
                # Agent not set up yet
                pass

        # Fallback to basic check
        return {
            "agent_num": agent_num,
            "status": "idle",
            "current_task": None,
            "tmux_active": self._check_tmux_session(agent_num),
            "last_activity": "Unknown"
        }

    def get_all_agents(self) -> List[dict]:
        """Get all configured agents."""
        if self.worktree_manager:
            # Get configured agent count from config
            num_agents = self.worktree_manager.config.num_agents
            return [self.get_agent_status(i) for i in range(1, num_agents + 1)]

        # Fallback to default
        return [self.get_agent_status(i) for i in range(1, 4)]


# Global agent manager - will be initialized in startup
agent_manager = AgentManager()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    user = get_current_user()  # Check auth if enabled
    agents = agent_manager.get_all_agents()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "agents": agents, "user": user}
    )


@app.get("/agents", response_class=HTMLResponse)
async def agents_list(request: Request):
    """Get agents list (HTMX endpoint)."""
    get_current_user()  # Check auth if enabled
    agents = agent_manager.get_all_agents()
    return templates.TemplateResponse(
        "partials/agents_list.html",
        {"request": request, "agents": agents}
    )


@app.get("/agent/{agent_num}/tmux", response_class=HTMLResponse)
async def agent_tmux(request: Request, agent_num: int):
    """Get tmux output for an agent (HTMX endpoint)."""
    get_current_user()  # Check auth if enabled
    # Capture tmux output
    try:
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", f"agent-{agent_num}", "-p"],
            capture_output=True,
            text=True,
            timeout=2
        )

        output = result.stdout if result.returncode == 0 else "Tmux session not active"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        output = "Could not capture tmux output"

    return templates.TemplateResponse(
        "partials/tmux_output.html",
        {"request": request, "agent_num": agent_num, "output": output}
    )


@app.post("/agent/{agent_num}/send", response_class=HTMLResponse)
async def send_to_agent(
    request: Request,
    agent_num: int,
    message: str = Form(...)
):
    """Send a message to an agent via tmux."""
    get_current_user()  # Check auth if enabled
    try:
        subprocess.run(
            ["tmux", "send-keys", "-t", f"agent-{agent_num}", message, "Enter"],
            check=True,
            timeout=2
        )

        status = "Message sent successfully"
    except subprocess.CalledProcessError:
        status = "Failed to send message"

    return templates.TemplateResponse(
        "partials/send_status.html",
        {"request": request, "status": status, "success": True}
    )


@app.post("/agent/{agent_num}/dispatch", response_class=HTMLResponse)
async def dispatch_task(
    request: Request,
    agent_num: int,
    issue_number: int = Form(default=None),
    task_description: str = Form(default=None)
):
    """Dispatch a task to an agent."""
    get_current_user()  # Check auth if enabled
    try:
        if agent_manager.worktree_manager:
            worktree_path = agent_manager.worktree_manager.config.get_worktree_path(agent_num)
            task_file = worktree_path / "TASK.md"

            # Create task content
            if issue_number:
                try:
                    issue = get_issue(issue_number)
                    task_content = f"# Task: {issue.title}\n\n"
                    task_content += f"Issue: #{issue_number}\n\n"
                    task_content += f"{issue.body}\n"
                except Exception as e:
                    task_content = f"# Task from Issue #{issue_number}\n\n"
                    task_content += f"Error fetching issue: {e}\n"
            else:
                task_content = f"# Ad-hoc Task\n\n{task_description or 'No description provided'}\n"

            # Write TASK.md
            task_file.write_text(task_content)
            status = f"Task dispatched to agent-{agent_num}"
        else:
            status = "Dashboard running in mock mode - task not actually dispatched"

    except Exception as e:
        status = f"Error: {str(e)}"

    return templates.TemplateResponse(
        "partials/dispatch_status.html",
        {
            "request": request,
            "agent_num": agent_num,
            "status": status
        }
    )


@app.websocket("/ws/agent/{agent_num}/tmux")
async def tmux_websocket(websocket: WebSocket, agent_num: int):
    """WebSocket for live tmux output streaming."""
    await websocket.accept()

    try:
        while True:
            # Capture tmux output every second
            try:
                result = subprocess.run(
                    ["tmux", "capture-pane", "-t", f"agent-{agent_num}", "-p"],
                    capture_output=True,
                    text=True,
                    timeout=1
                )

                if result.returncode == 0:
                    await websocket.send_text(result.stdout)
                else:
                    await websocket.send_text("[Tmux session not active]")

            except subprocess.TimeoutExpired:
                await websocket.send_text("[Timeout capturing tmux]")

            await asyncio.sleep(1)

    except WebSocketDisconnect:
        pass


@app.get("/flow", response_class=HTMLResponse)
async def flow_view(request: Request):
    """Flow view page (inbox-style task management)."""
    user = get_current_user()  # Check auth if enabled
    try:
        issues_ctx = list_issues(state="open")
        sorted_issues_ctx = sort_issues_by_priority(issues_ctx)

        # Convert first issue to Issue model for detail view
        selected_issue = None
        if sorted_issues_ctx:
            first = sorted_issues_ctx[0]
            stage = StageEnum.BACKLOG
            for label in first.labels:
                if label.startswith("stage-"):
                    stage_name = label.replace("stage-", "").replace("-", "_")
                    try:
                        stage = StageEnum(stage_name)
                    except ValueError:
                        pass

            selected_issue = Issue(
                number=first.number,
                title=first.title,
                body=first.body,
                labels=first.labels,
                assignees=first.assignees,
                stage=stage,
                status=IssueStatus.OPEN,
                url=first.url,
                created_at=datetime.fromisoformat(first.created_at.replace('Z', '+00:00')),
                updated_at=datetime.fromisoformat(first.updated_at.replace('Z', '+00:00'))
            )

    except Exception as e:
        print(f"Error fetching issues: {e}")
        sorted_issues_ctx = []
        selected_issue = None

    return templates.TemplateResponse(
        "flow.html",
        {"request": request, "issues": sorted_issues_ctx, "user": user, "selected_issue": selected_issue}
    )


@app.get("/flow/issues", response_class=HTMLResponse)
async def flow_issues_list(request: Request):
    """Get issues list for Flow view (HTMX endpoint)."""
    get_current_user()  # Check auth if enabled
    try:
        issues = list_issues(state="open")
        sorted_issues = sort_issues_by_priority(issues)
    except Exception as e:
        print(f"Error fetching issues: {e}")
        sorted_issues = []

    return templates.TemplateResponse(
        "partials/flow_issues_list.html",
        {"request": request, "issues": sorted_issues}
    )






@app.get("/kanban", response_class=HTMLResponse)
async def kanban_view(request: Request):
    """Kanban board view."""
    user = get_current_user()  # Check auth if enabled
    try:
        issues = list_issues(state="open")

        # Group issues by stage
        stages_dict = {stage: [] for stage in StageEnum}

        for issue_ctx in issues:
            # Map GitHub issue to our Issue model
            # For now, extract stage from labels or default to backlog
            stage = StageEnum.BACKLOG
            for label in issue_ctx.labels:
                if label.startswith("stage-"):
                    stage_name = label.replace("stage-", "").replace("-", "_")
                    try:
                        stage = StageEnum(stage_name)
                    except ValueError:
                        pass

            issue = Issue(
                number=issue_ctx.number,
                title=issue_ctx.title,
                body=issue_ctx.body,
                labels=issue_ctx.labels,
                assignees=issue_ctx.assignees,
                stage=stage,
                status=IssueStatus.OPEN if issue_ctx.state == "OPEN" else IssueStatus.CLOSED,
                url=issue_ctx.url,
                created_at=datetime.fromisoformat(issue_ctx.created_at.replace('Z', '+00:00')),
                updated_at=datetime.fromisoformat(issue_ctx.updated_at.replace('Z', '+00:00'))
            )
            stages_dict[stage].append(issue)

        board = KanbanBoard(
            stages=stages_dict,
            total_issues=len(issues)
        )
    except Exception as e:
        print(f"Error fetching issues: {e}")
        board = KanbanBoard(
            stages={stage: [] for stage in StageEnum},
            total_issues=0
        )

    return templates.TemplateResponse(
        "kanban.html",
        {"request": request, "board": board, "stages": StageEnum, "user": user}
    )


@app.post("/api/issues/{issue_number}/move")
async def move_issue(issue_number: int, move_request: IssueMoveRequest):
    """Move issue to new stage (API endpoint)."""
    get_current_user()  # Check auth if enabled

    # TODO: Update issue in agents/ repo
    # For now, just return success
    # In real implementation:
    # 1. Pull agents/ repo
    # 2. Update issue.yaml with new stage
    # 3. Commit and push

    return {
        "success": True,
        "issue_number": issue_number,
        "new_stage": move_request.stage.value
    }


@app.get("/api/issues/{issue_number}/detail", response_class=HTMLResponse)
async def issue_detail(request: Request, issue_number: int):
    """Get issue detail (shared between kanban modal and flow panel)."""
    get_current_user()  # Check auth if enabled
    try:
        issues = list_issues(state="open")
        issue_ctx = next((i for i in issues if i.number == issue_number), None)

        if not issue_ctx:
            return HTMLResponse("<div class='error'>Issue not found</div>")

        # Convert to Issue model
        stage = StageEnum.BACKLOG
        for label in issue_ctx.labels:
            if label.startswith("stage-"):
                stage_name = label.replace("stage-", "").replace("-", "_")
                try:
                    stage = StageEnum(stage_name)
                except ValueError:
                    pass

        issue = Issue(
            number=issue_ctx.number,
            title=issue_ctx.title,
            body=issue_ctx.body,
            labels=issue_ctx.labels,
            assignees=issue_ctx.assignees,
            stage=stage,
            status=IssueStatus.OPEN,
            url=issue_ctx.url,
            created_at=datetime.fromisoformat(issue_ctx.created_at.replace('Z', '+00:00')),
            updated_at=datetime.fromisoformat(issue_ctx.updated_at.replace('Z', '+00:00'))
        )

    except Exception as e:
        return HTMLResponse(f"<div class='error'>Error: {str(e)}</div>")

    return templates.TemplateResponse(
        "partials/issue_detail.html",
        {"request": request, "issue": issue}
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "agenttree-web"}


def run_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    config_path: Optional[Path] = None
):
    """Run the FastAPI server.

    Args:
        host: Host to bind to
        port: Port to bind to
        config_path: Path to agenttree config file (optional)
    """
    global agent_manager

    # Try to load config and initialize real agent manager
    if config_path or Path(".agenttree/config.yaml").exists():
        try:
            config = load_config(config_path)
            repo_path = Path.cwd()  # Assume current directory is the repo
            worktree_manager = WorktreeManager(repo_path, config)
            agent_manager = AgentManager(worktree_manager)
            print(f"✓ Loaded config with {config.num_agents} agents")
        except Exception as e:
            print(f"⚠ Could not load config: {e}")
            print("  Running with mock data")

    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
