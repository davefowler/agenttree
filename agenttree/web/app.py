"""Web dashboard for AgentTree using FastAPI + HTMX."""

# Force standard asyncio event loop instead of uvloop to avoid fork crashes
# uvloop's signal handlers aren't fork-safe, causing crashes when subprocess.run() forks
import asyncio

asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from agenttree.config import load_config
from agenttree.web.agent_manager import AgentManager, agent_manager
from agenttree.web.deps import BASE_DIR
from agenttree.web.routes import agents, issues, pages, rate_limit, settings, voice
from agenttree.worktree import WorktreeManager

# Re-export for backward compatibility with tests that patch these
from agenttree import issues as issue_crud  # noqa: F401
from agenttree.web.utils import (  # noqa: F401
    FILE_TO_STAGE,
    STAGE_FILE_ORDER,
    _config,
    _filter_flow_issues,
    _sort_flow_issues,
    convert_issue_to_web,
    filter_issues,
    format_duration,
    get_default_doc,
    get_issue_diff,
    get_issue_files,
    get_kanban_board,
)

# Background heartbeat task handle
_heartbeat_task: Optional[asyncio.Task] = None
_heartbeat_count: int = 0

# Dedicated executor for heartbeat so it never competes with request handlers.
# Heartbeat actions (sync, check_ci, check_stalled) can take 10-15s and would
# starve asyncio.to_thread() calls in request handlers if sharing the default pool.
_heartbeat_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="heartbeat")


async def heartbeat_loop(interval: int = 10) -> None:
    """Background task that fires heartbeat events periodically.

    The heartbeat event triggers configured actions like:
    - sync: Git pull/push _agenttree
    - check_stalled_agents: Nudge agents stuck too long
    - check_ci_status: Check GitHub CI status
    - check_merged_prs: Detect externally merged PRs

    Actions are configured in .agenttree.yaml under on.heartbeat.

    Args:
        interval: Seconds between heartbeats (default: 10)
    """
    global _heartbeat_count
    from agenttree.events import HEARTBEAT, fire_event

    agents_dir = Path.cwd() / "_agenttree"

    while True:
        try:
            _heartbeat_count += 1
            await asyncio.get_event_loop().run_in_executor(
                _heartbeat_executor,
                lambda: fire_event(HEARTBEAT, agents_dir, heartbeat_count=_heartbeat_count),
            )
        except Exception as e:
            print(f"Heartbeat error: {e}")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan context - starts heartbeat and manager.

    Note: The startup event is fired by 'agenttree start' before starting the server.
    This lifespan only handles the heartbeat loop and manager startup fallback.
    """
    global _heartbeat_task

    # Get heartbeat interval from config
    from agenttree.events import get_heartbeat_interval

    interval = get_heartbeat_interval()

    # Start heartbeat task
    _heartbeat_task = asyncio.create_task(heartbeat_loop(interval))
    print(f"✓ Started heartbeat events (every {interval}s)")

    # Auto-start manager if not running (fallback for direct server start)
    from agenttree.tmux import session_exists

    config = load_config()
    manager_session = config.get_manager_tmux_session()
    if not session_exists(manager_session):
        try:
            from agenttree.api import start_controller

            await asyncio.to_thread(start_controller, quiet=True)
            print("✓ Started controller agent")
        except Exception as e:
            print(f"⚠ Could not start controller: {e}")
    else:
        print("✓ Manager already running")

    yield  # Server runs here

    # Cleanup on shutdown
    if _heartbeat_task:
        _heartbeat_task.cancel()
        try:
            await _heartbeat_task
        except asyncio.CancelledError:
            pass
    print("✓ Stopped heartbeat events")


app = FastAPI(title="AgentTree Dashboard", lifespan=lifespan)


class NoCacheMiddleware(BaseHTTPMiddleware):
    """Disable caching for HTML responses during development."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable["Response"]]
    ) -> "Response":
        response = await call_next(request)
        # Disable cache for HTML responses
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


app.add_middleware(NoCacheMiddleware)

# Mount static files
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Include route modules
app.include_router(pages.router)
app.include_router(agents.router)
app.include_router(issues.router)
app.include_router(rate_limit.router)
app.include_router(settings.router)
app.include_router(voice.router)


def run_server(
    host: str = "0.0.0.0",
    port: int = 8080,
    config_path: Optional[Path] = None,
) -> None:
    """Run the FastAPI server.

    Args:
        host: Host to bind to
        port: Port to bind to
        config_path: Path to agenttree config file (optional)
    """
    # Import here to avoid circular imports
    from agenttree.web import agent_manager as am_module

    # Load config - find_config_file walks up directory tree to find .agenttree.yaml
    try:
        config = load_config(config_path)
        repo_path = Path.cwd()
        # Set env so uvicorn workers (which may have different cwd) can find config
        os.environ["AGENTTREE_REPO_PATH"] = str(repo_path)
        worktree_manager = WorktreeManager(repo_path, config)
        # Update the global agent_manager with worktree_manager
        am_module.agent_manager = AgentManager(worktree_manager)
        print(f"✓ Loaded config for project: {config.project}")
    except Exception as e:
        print(f"⚠ Could not load config: {e}")
        print("  Run 'agenttree init' to create a config file")

    import uvicorn

    # Single worker — the heartbeat (sync, manager hooks, stall detection) must run
    # in exactly one process. Multiple workers cause 4x duplicate operations and race
    # conditions on YAML files. One async worker handles the dashboard just fine.
    uvicorn.run(
        "agenttree.web.app:app", host=host, port=port, workers=1, loop="asyncio"
    )


if __name__ == "__main__":
    run_server()
