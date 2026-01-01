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

# Get the directory where this file is located
BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="AgentTree Dashboard")

# Mount static files and templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Optional authentication
security = HTTPBasic()

# Auth configuration from environment variables
AUTH_ENABLED = os.getenv("AGENTTREE_WEB_AUTH", "false").lower() == "true"
AUTH_USERNAME = os.getenv("AGENTTREE_WEB_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AGENTTREE_WEB_PASSWORD", "changeme")


def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> Optional[str]:
    """Verify HTTP Basic Auth credentials.

    Returns username if valid, raises HTTPException if invalid.
    Only enforced if AUTH_ENABLED=true.
    """
    if not AUTH_ENABLED:
        return None

    # Constant-time comparison to prevent timing attacks
    username_correct = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        AUTH_USERNAME.encode("utf-8")
    )
    password_correct = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        AUTH_PASSWORD.encode("utf-8")
    )

    if not (username_correct and password_correct):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


# Dependency for protected routes
def get_current_user(username: Optional[str] = Depends(verify_credentials)) -> Optional[str]:
    """Get current authenticated user (or None if auth disabled)."""
    return username


class AgentManager:
    """Manages agent state for the dashboard."""

    def __init__(self):
        self.agents: Dict[int, dict] = {}

    def get_agent_status(self, agent_num: int) -> dict:
        """Get status of an agent."""
        # This would integrate with actual worktree manager
        # For now, mock it
        return {
            "agent_num": agent_num,
            "status": "idle",
            "current_task": None,
            "tmux_active": True,
            "last_activity": datetime.now().isoformat()
        }

    def get_all_agents(self) -> List[dict]:
        """Get all configured agents."""
        # Mock for now
        return [self.get_agent_status(i) for i in range(1, 4)]


agent_manager = AgentManager()


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: Optional[str] = Depends(get_current_user)):
    """Main dashboard page."""
    agents = agent_manager.get_all_agents()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "agents": agents, "user": user}
    )


@app.get("/agents", response_class=HTMLResponse)
async def agents_list(request: Request, user: Optional[str] = Depends(get_current_user)):
    """Get agents list (HTMX endpoint)."""
    agents = agent_manager.get_all_agents()
    return templates.TemplateResponse(
        "partials/agents_list.html",
        {"request": request, "agents": agents}
    )


@app.get("/agent/{agent_num}/tmux", response_class=HTMLResponse)
async def agent_tmux(
    request: Request,
    agent_num: int,
    user: Optional[str] = Depends(get_current_user)
):
    """Get tmux output for an agent (HTMX endpoint)."""
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
    message: str = Form(...),
    user: Optional[str] = Depends(get_current_user)
):
    """Send a message to an agent via tmux."""
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
    task_description: str = Form(default=None),
    user: Optional[str] = Depends(get_current_user)
):
    """Dispatch a task to an agent."""
    # This would integrate with actual dispatch logic
    # For now, just show success
    return templates.TemplateResponse(
        "partials/dispatch_status.html",
        {
            "request": request,
            "agent_num": agent_num,
            "status": f"Task dispatched to agent-{agent_num}"
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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "agenttree-web"}


def run_server(host: str = "127.0.0.1", port: int = 8080):
    """Run the FastAPI server.

    Args:
        host: Host to bind to
        port: Port to bind to
    """
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
