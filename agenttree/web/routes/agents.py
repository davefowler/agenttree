"""Agent tmux routes."""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from agenttree.config import load_config
from agenttree.web.deps import get_current_user, templates
from agenttree.web.utils import _capture_tmux_output, _compute_etag, _strip_claude_input_prompt

router = APIRouter()
logger = logging.getLogger("agenttree.web")


@router.get("/agent/{agent_num}/tmux", response_class=HTMLResponse)
async def agent_tmux(
    request: Request,
    agent_num: str,
    user: str | None = Depends(get_current_user),
) -> Response:
    """Get tmux output for an issue's agent (HTMX endpoint).

    Note: agent_num parameter is actually the issue number - sessions are named by issue.

    Returns ETag header for conditional requests. If client sends If-None-Match
    with matching ETag, returns 304 Not Modified to save bandwidth.
    """
    from agenttree.ids import parse_issue_id
    from agenttree.tmux import is_claude_running

    config = load_config()
    issue_id = parse_issue_id(agent_num)
    session_names = config.get_issue_session_patterns(issue_id)

    # Capture tmux output in thread pool to avoid blocking event loop
    raw_output, session_name = await asyncio.to_thread(
        _capture_tmux_output, session_names
    )

    if raw_output and session_name:
        # Strip Claude Code's input prompt separator from the output
        output = _strip_claude_input_prompt(raw_output)
        # Check if Claude is actually running (not just tmux session)
        is_running = await asyncio.to_thread(is_claude_running, session_name)
        claude_status = "running" if is_running else "exited"
    else:
        output = "Tmux session not active"
        claude_status = "no_session"

    # Compute ETag from stripped output
    etag = _compute_etag(output)

    # Check If-None-Match header for conditional request
    if_none_match = request.headers.get("If-None-Match")
    if if_none_match and if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})

    # Render template and return with ETag
    html_content = templates.TemplateResponse(
        "partials/tmux_output.html",
        {
            "request": request,
            "agent_num": agent_num,
            "output": output,
            "claude_status": claude_status,
        },
    )
    html_content.headers["ETag"] = etag
    return html_content


@router.post("/agent/{agent_num}/send", response_class=HTMLResponse)
async def send_to_agent(
    request: Request,
    agent_num: str,
    message: str = Form(...),
    user: str | None = Depends(get_current_user),
) -> HTMLResponse:
    """Send a message to an issue's agent via tmux.

    Note: agent_num parameter is actually the issue number - sessions are named by issue.
    """
    from agenttree.ids import parse_issue_id
    from agenttree.tmux import send_message, session_exists

    # Log all messages sent via web UI for debugging mystery messages
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")[:100]
    logger.info(
        f"[SEND] issue={agent_num} msg={message!r} "
        f"ip={client_ip} ua={user_agent} time={datetime.now().isoformat()}"
    )

    config = load_config()
    issue_id = parse_issue_id(agent_num)

    # Find the active session using config patterns
    session_patterns = config.get_issue_session_patterns(issue_id)
    session_name = next(
        (n for n in session_patterns if session_exists(n)), session_patterns[0]
    )

    # Send message - result will appear in tmux output on next poll
    result = send_message(session_name, message)

    # Log if Claude isn't running
    if result == "claude_exited":
        logger.warning(
            f"[SEND] Claude exited for issue={agent_num}, message went to shell"
        )

    return HTMLResponse("")
