"""Issue API routes."""

import asyncio
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from agenttree import issues as issue_crud
from agenttree.config import load_config
from agenttree.web.agent_manager import agent_manager
from agenttree.web.deps import get_current_user
from agenttree.web.models import IssueMoveRequest, PriorityUpdateRequest
from agenttree.web.utils import get_issue_diff

router = APIRouter(prefix="/api/issues", tags=["issues"])
logger = logging.getLogger("agenttree.web")

# Load config at module level
_config = load_config()

# Allowed file extensions for attachments
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",  # Images
    ".txt",
    ".log",
    ".md",
    ".json",
    ".yaml",
    ".yml",  # Text files
}
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("")
async def create_issue_api(
    request: Request,
    description: str = Form(""),
    title: str = Form(""),
    files: list[UploadFile] = File(default=[]),
    user: str | None = Depends(get_current_user),
) -> dict:
    """Create a new issue via the web UI.

    Creates a new issue with the default starting stage.
    If no title is provided, one is auto-generated from the description.
    Accepts optional file attachments.
    """
    from agenttree.api import start_agent
    from agenttree.issues import Priority

    description = description.strip()
    title = title.strip()

    # Require at least a description
    if not description:
        raise HTTPException(status_code=400, detail="Please provide a description")

    # Use placeholder if no title - agent will fill it in during define stage
    if not title:
        title = "(untitled)"

    # Validate and read attachments
    attachments: list[tuple[str, bytes]] = []
    for file in files:
        if not file.filename:
            continue

        # Check file extension
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_ATTACHMENT_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"File type '{ext}' not allowed. Allowed types: {', '.join(sorted(ALLOWED_ATTACHMENT_EXTENSIONS))}",
            )

        # Read and check size
        content = await file.read()
        if len(content) > MAX_ATTACHMENT_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File '{file.filename}' exceeds maximum size of 10MB",
            )

        attachments.append((file.filename, content))

    try:
        issue = issue_crud.create_issue(
            title=title,
            priority=Priority.MEDIUM,
            problem=description,
            attachments=attachments or None,
        )

        # Auto-start agent for the new issue
        try:
            await asyncio.to_thread(start_agent, issue.id, quiet=True)
        except Exception as e:
            # Log but don't fail - issue was created, agent start is optional
            print(f"Warning: Could not auto-start agent for issue #{issue.id}: {e}")

        return {"ok": True, "issue_id": issue.id, "title": issue.title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{issue_id}/start")
async def start_issue(
    issue_id: str, user: str | None = Depends(get_current_user)
) -> dict:
    """Start an agent to work on an issue."""
    from agenttree.api import AgentStartError, IssueNotFoundError, start_agent

    try:
        # Use force=True to restart stalled agents (tmux dead but state exists)
        await asyncio.to_thread(start_agent, issue_id, force=True, quiet=True)
        return {"ok": True, "status": f"Started agent for issue #{issue_id}"}
    except IssueNotFoundError:
        raise HTTPException(status_code=404, detail=f"Issue #{issue_id} not found")
    except AgentStartError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{issue_id}/stop")
async def stop_issue(
    issue_id: str, user: str | None = Depends(get_current_user)
) -> dict:
    """Stop an agent working on an issue (kills tmux, stops container, cleans up state)."""
    from agenttree.api import stop_all_agents_for_issue
    from agenttree.ids import parse_issue_id

    try:
        parsed_id = parse_issue_id(issue_id)
        # Run in thread to avoid blocking event loop
        count = await asyncio.to_thread(stop_all_agents_for_issue, parsed_id, quiet=True)
        if count > 0:
            return {
                "ok": True,
                "status": f"Stopped {count} agent(s) for issue #{issue_id}",
            }
        else:
            return {"ok": True, "status": f"No active agents for issue #{issue_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{issue_id}/agent-status")
async def get_agent_status(
    issue_id: str, user: str | None = Depends(get_current_user)
) -> dict:
    """Check if an agent's tmux session is running for an issue."""
    from agenttree.ids import parse_issue_id

    parsed_id = parse_issue_id(issue_id)

    # For human review stages, check the developer agent session
    issue = issue_crud.get_issue(parsed_id, sync=False)
    if issue and _config.is_human_review(issue.stage):
        dev_session = _config.get_issue_tmux_session(parsed_id, "developer")
        tmux_active = await asyncio.to_thread(
            lambda: dev_session in agent_manager._get_active_sessions()
        )
    else:
        tmux_active = await asyncio.to_thread(
            agent_manager._check_issue_tmux_session, parsed_id
        )

    processing = issue.processing if issue else None

    return {
        "tmux_active": tmux_active,
        "status": "running" if tmux_active else "off",
        "processing": processing,
    }


@router.get("/{issue_id}/diff")
async def get_diff(
    issue_id: str, user: str | None = Depends(get_current_user)
) -> dict:
    """Get git diff for an issue's worktree.

    Returns the raw diff output for rendering with diff2html on the client.
    """
    from agenttree.ids import parse_issue_id

    parsed_id = parse_issue_id(issue_id)

    # Check issue exists
    issue = issue_crud.get_issue(parsed_id)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Get diff in thread pool to avoid blocking event loop
    return await asyncio.to_thread(get_issue_diff, parsed_id)


@router.post("/{issue_id}/move")
async def move_issue(
    issue_id: str,
    move_request: IssueMoveRequest,
    user: str | None = Depends(get_current_user),
) -> dict:
    """Move an issue to a new stage.

    DEPRECATED: Use /approve for human review stages instead.
    This bypasses workflow validation and should only be used for backlog management.
    """
    # Only allow moving TO parking-lot stages (safe operations)
    parking_lots = _config.get_parking_lot_stages()
    if move_request.stage not in parking_lots:
        raise HTTPException(
            status_code=400,
            detail=f"Direct stage changes only allowed to: {', '.join(sorted(parking_lots))}. Use approve for workflow transitions.",
        )

    # Get issue first to pass to cleanup
    issue = issue_crud.get_issue(issue_id, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    updated_issue = issue_crud.update_issue_stage(
        issue_id=issue_id,
        stage=move_request.stage,
    )

    if not updated_issue:
        raise HTTPException(
            status_code=500, detail=f"Failed to update issue {issue_id}"
        )

    # Clean up agent when moving to parking-lot stages
    # backlog = pause work (stop agent, keep worktree for later)
    # not_doing = abandon work (stop agent, worktree can be cleaned up)
    if _config.is_parking_lot(move_request.stage):
        from agenttree.hooks import cleanup_issue_agent

        # Run cleanup in thread to avoid blocking event loop
        await asyncio.to_thread(cleanup_issue_agent, updated_issue)

    return {"success": True, "stage": move_request.stage}


@router.post("/{issue_id}/approve")
async def approve_issue(
    issue_id: str, user: str | None = Depends(get_current_user)
) -> dict:
    """Approve an issue at a human review stage.

    Uses api.transition_issue() for consistent exit hooks -> stage update -> enter hooks.
    Only works from human review stages.
    """
    from agenttree.hooks import StageRedirect, ValidationError

    # Get issue
    issue = issue_crud.get_issue(issue_id, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    # Load config from repo path (Path.cwd() can be wrong in uvicorn workers)
    config_path = (
        Path(os.environ["AGENTTREE_REPO_PATH"])
        if os.environ.get("AGENTTREE_REPO_PATH")
        else None
    )
    config = load_config(config_path)

    # Check if at human review stage
    if not config.is_human_review(issue.stage):
        raise HTTPException(status_code=400, detail="Not at review stage")

    next_stage, _ = config.get_next_stage(issue.stage, issue.flow)

    try:
        # Set processing state
        issue_crud.set_processing(issue_id, "exit")

        # Use consolidated transition_issue() — handles exit hooks, stage update, enter hooks
        from agenttree.api import transition_issue

        try:
            await asyncio.to_thread(
                transition_issue,
                issue_id,
                next_stage,
                skip_pr_approval=config.allow_self_approval,
                trigger="web",
            )
        except StageRedirect as redirect:
            # Redirect — retry with new target
            await asyncio.to_thread(
                transition_issue,
                issue_id,
                redirect.target,
                skip_pr_approval=config.allow_self_approval,
                trigger="web",
            )
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Notify agent to continue (if active)
        try:
            from agenttree.state import get_active_agent
            from agenttree.tmux import send_message, session_exists

            agent = get_active_agent(issue.id)
            if agent and agent.tmux_session:
                if session_exists(agent.tmux_session):
                    message = (
                        "Your work was approved! Run `agenttree next` for instructions."
                    )
                    await asyncio.to_thread(send_message, agent.tmux_session, message)
        except Exception as e:
            logger.warning("Agent notification failed for issue %s: %s", issue_id, e)

        return {"ok": True}
    except HTTPException:
        raise  # Let FastAPI handle these with proper status codes
    except Exception as e:
        logger.exception(f"Error approving issue #{issue_id}")
        raise HTTPException(
            status_code=500, detail=f"Internal error: {type(e).__name__}: {e}"
        )
    finally:
        # Always clear processing state
        issue_crud.set_processing(issue_id, None)


@router.get("/{issue_id}/attachments/{filename:path}")
async def get_attachment(
    issue_id: str,
    filename: str,
    user: str | None = Depends(get_current_user),
) -> FileResponse:
    """Serve an attachment file for an issue.

    Used to display images in markdown previews and allow file downloads.
    """
    from agenttree.issues import get_issue_dir

    # Get issue directory
    issue_dir = get_issue_dir(issue_id)
    if not issue_dir:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Build attachment path
    attachments_dir = issue_dir / "attachments"
    file_path = attachments_dir / filename

    # Security: Ensure the resolved path is within the attachments directory
    try:
        resolved_path = file_path.resolve()
        resolved_attachments = attachments_dir.resolve()
        if not resolved_path.is_relative_to(resolved_attachments):
            raise HTTPException(status_code=400, detail="Invalid filename")
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Check if file exists
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Attachment '{filename}' not found")

    return FileResponse(file_path)


@router.delete("/{issue_id}/dependencies/{dep_id}")
async def remove_dependency(
    issue_id: str, dep_id: str, user: str | None = Depends(get_current_user)
) -> dict:
    """Remove a dependency from an issue."""
    from agenttree.issues import remove_dependency as remove_dep

    try:
        issue = remove_dep(issue_id, dep_id)
        if not issue:
            raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
        return {"ok": True, "issue_id": issue.id, "dependencies": issue.dependencies}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{issue_id}/priority")
async def update_issue_priority(
    issue_id: str,
    request: PriorityUpdateRequest,
    user: str | None = Depends(get_current_user),
) -> dict:
    """Update an issue's priority."""
    from agenttree.issues import Priority
    from agenttree.issues import update_issue_priority as do_update_priority

    # Validate priority value
    valid_priorities = [p.value for p in Priority]
    if request.priority not in valid_priorities:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority '{request.priority}'. Must be one of: {', '.join(valid_priorities)}",
        )

    # Get and update issue
    issue = issue_crud.get_issue(issue_id, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    updated = do_update_priority(issue.id, Priority(request.priority))
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update priority")

    return {"ok": True, "priority": request.priority}


@router.post("/{issue_id}/rebase")
async def rebase_issue(
    issue_id: str, user: str | None = Depends(get_current_user)
) -> dict:
    """Rebase an issue's branch onto the latest main.

    Performs the rebase and notifies the agent. Client reloads page after.
    """
    from agenttree.hooks import rebase_issue_branch
    from agenttree.ids import parse_issue_id
    from agenttree.tmux import send_message, session_exists

    # Get issue
    issue = issue_crud.get_issue(issue_id, sync=False)
    if not issue:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")

    # Perform the rebase
    success, message = rebase_issue_branch(issue_id)

    if not success:
        raise HTTPException(status_code=400, detail=message)

    # Notify the agent if there's an active tmux session
    config = load_config()
    parsed_id = parse_issue_id(issue_id)

    # Find active session using config patterns
    session_name = None
    for pattern in config.get_issue_session_patterns(parsed_id):
        if session_exists(pattern):
            session_name = pattern
            break

    if session_name:
        notification = (
            "Your branch has been rebased onto the latest main. "
            "Please review the recent changes and update your work if needed. "
            "Run 'git log --oneline -10' to see recent commits."
        )
        send_message(session_name, notification)

    return {"ok": True}
