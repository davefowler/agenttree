"""Rate limit API routes."""

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from agenttree.actions import load_rate_limit_state, save_rate_limit_state
from agenttree.config import load_config
from agenttree.web.deps import get_current_user

router = APIRouter(prefix="/api", tags=["rate-limit"])


@router.get("/rate-limit-status")
async def get_rate_limit_status(
    user: str | None = Depends(get_current_user),
) -> dict:
    """Get current rate limit status.

    Returns:
        {
            "rate_limited": bool,
            "reset_time": str | None (ISO timestamp),
            "mode": "subscription" | "api_key",
            "affected_agents": list[{issue_id, session_name}],
            "can_switch_to_api": bool (True if ANTHROPIC_API_KEY is set)
        }
    """
    config = load_config()
    agents_dir = Path("_agenttree")

    state = load_rate_limit_state(agents_dir)

    # Check if API key is available for switching
    api_key_available = bool(os.environ.get(config.rate_limit_fallback.api_key_env))

    if not state:
        return {
            "rate_limited": False,
            "reset_time": None,
            "mode": "subscription",
            "affected_agents": [],
            "can_switch_to_api": api_key_available,
        }

    return {
        "rate_limited": state.get("rate_limited", False),
        "reset_time": state.get("reset_time"),
        "mode": state.get("mode", "subscription"),
        "affected_agents": state.get("affected_agents", []),
        "can_switch_to_api": api_key_available,
    }


@router.post("/rate-limit/switch-to-api")
async def switch_to_api_key_mode(
    user: str | None = Depends(get_current_user),
) -> dict:
    """Switch all rate-limited agents to API key mode.

    This is a manual trigger - user clicks button in UI when they want to
    start paying API costs to unblock their agents.
    """
    config = load_config()
    agents_dir = Path("_agenttree")

    # Check if API key is available
    api_key = os.environ.get(config.rate_limit_fallback.api_key_env)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"API key not configured. Set {config.rate_limit_fallback.api_key_env} environment variable.",
        )

    # Load current state
    state = load_rate_limit_state(agents_dir)
    if not state or not state.get("rate_limited"):
        raise HTTPException(status_code=400, detail="No rate limit currently detected")

    if state.get("mode") == "api_key":
        raise HTTPException(status_code=400, detail="Already running in API key mode")

    # Restart all affected agents with --api-key flag
    affected_agents = state.get("affected_agents", [])
    restarted = 0
    failed = []

    for agent_info in affected_agents:
        issue_id = agent_info.get("issue_id")
        if not issue_id:
            continue

        result = subprocess.run(
            [
                "agenttree",
                "start",
                str(issue_id),
                "--api-key",
                "--skip-preflight",
                "--force",
            ],
            capture_output=True,
            text=True,
            timeout=120,  # Container startup can be slow
        )
        if result.returncode == 0:
            restarted += 1
        else:
            failed.append({"issue_id": issue_id, "error": result.stderr[:200]})

    # Update state to reflect API key mode
    state["mode"] = "api_key"
    state["switched_at"] = datetime.now(timezone.utc).isoformat()
    save_rate_limit_state(agents_dir, state)

    return {
        "ok": True,
        "restarted": restarted,
        "failed": failed,
        "message": f"Switched {restarted} agent(s) to API key mode",
    }


@router.post("/rate-limit/dismiss")
async def dismiss_rate_limit(
    user: str | None = Depends(get_current_user),
) -> dict:
    """Dismiss the rate limit warning without switching modes.

    Agents remain blocked but the UI warning is dismissed.
    The auto-recovery will still trigger after reset time.
    """
    agents_dir = Path("_agenttree")
    state = load_rate_limit_state(agents_dir)

    if state:
        state["dismissed"] = True
        save_rate_limit_state(agents_dir, state)

    return {"ok": True}
