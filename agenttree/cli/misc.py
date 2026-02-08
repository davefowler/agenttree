"""Miscellaneous commands (auto-merge, context-init, tui, cleanup)."""

import subprocess
import sys
from pathlib import Path

import click

from agenttree.cli._utils import console, load_config, get_issue_func, Config
from agenttree.container import get_container_runtime
from agenttree.github import ensure_gh_cli
from agenttree.hooks import is_running_in_container
from agenttree.issues import list_issues as list_issues_func, BACKLOG


@click.command()
@click.argument("pr_number", type=int)
@click.option("--no-approval", is_flag=True, help="Skip approval requirement")
@click.option("--monitor", is_flag=True, help="Monitor PR until ready to merge")
@click.option("--timeout", default=3600, type=int, help="Max wait time in seconds (for --monitor)")
def auto_merge(pr_number: int, no_approval: bool, monitor: bool, timeout: int) -> None:
    """Auto-merge a PR when CI passes and approved.

    Examples:
        agenttree auto-merge 123                    # Check once, merge if ready
        agenttree auto-merge 123 --monitor          # Wait for CI + approval
        agenttree auto-merge 123 --no-approval      # Merge when CI passes (skip approval check)
    """
    from agenttree.github import auto_merge_if_ready, monitor_pr_and_auto_merge

    ensure_gh_cli()

    if monitor:
        console.print(f"[cyan]Monitoring PR #{pr_number}...[/cyan]")
        console.print(f"[dim]Will auto-merge when CI passes{'  and approved' if not no_approval else ''}[/dim]\n")

        success = monitor_pr_and_auto_merge(
            pr_number,
            require_approval=not no_approval,
            max_wait=timeout
        )

        if success:
            console.print(f"[green]✓ PR #{pr_number} auto-merged successfully![/green]")
        else:
            console.print(f"[yellow]⚠ PR #{pr_number} not ready or timed out[/yellow]")
            sys.exit(1)
    else:
        console.print(f"[cyan]Checking PR #{pr_number}...[/cyan]")

        if auto_merge_if_ready(pr_number, require_approval=not no_approval):
            console.print(f"[green]✓ PR #{pr_number} merged![/green]")
        else:
            console.print(f"[yellow]⚠ PR #{pr_number} not ready to merge[/yellow]")
            console.print("[dim]Use --monitor to wait for CI + approval[/dim]")
            sys.exit(1)


@click.command("context-init")
@click.option("--agent", "-a", "agent_num", type=int, help="Agent number (reads from .env if not provided)")
@click.option("--port", "-p", "port", type=int, help="Agent port (derived from agent number if not provided)")
def context_init(agent_num: int | None, port: int | None) -> None:
    """Initialize agent context in current worktree.

    This command:
    1. Clones the _agenttree repo into the current directory
    2. Verifies/creates agent identity (.env with AGENT_NUM, PORT)

    Run this from within an agent worktree during setup.

    Examples:
        agenttree context-init --agent 1
        agenttree context-init  # Reads agent number from .env
    """
    cwd = Path.cwd()

    # Try to read agent number from .env if not provided
    if agent_num is None:
        env_file = cwd / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("AGENT_NUM="):
                    try:
                        agent_num = int(line.split("=")[1].strip())
                        console.print(f"[dim]Found AGENT_NUM={agent_num} in .env[/dim]")
                    except ValueError:
                        pass

    if agent_num is None:
        console.print("[red]Error: No agent number provided and none found in .env[/red]")
        console.print("[dim]Use --agent <N> or ensure .env contains AGENT_NUM=<N>[/dim]")
        sys.exit(1)

    # Calculate port if not provided
    if port is None:
        config = load_config()
        port = config.get_port_for_agent(agent_num)

    # Check if _agenttree already exists
    agenttrees_path = cwd / "_agenttree"
    if agenttrees_path.exists() and (agenttrees_path / ".git").exists():
        console.print(f"[green]✓ _agenttree already exists[/green]")
    else:
        # Try to find the remote URL from the main project
        # Go up directories to find the main _agenttree repo
        main_agenttrees = None
        parent = cwd.parent
        for _ in range(5):  # Check up to 5 levels up
            candidate = parent / "_agenttree"
            if candidate.exists() and (candidate / ".git").exists():
                main_agenttrees = candidate
                break
            parent = parent.parent

        if main_agenttrees is None:
            console.print("[red]Error: Could not find main _agenttree repo[/red]")
            console.print("[dim]Make sure you're in an agent worktree[/dim]")
            sys.exit(1)

        # Get the remote URL
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=main_agenttrees,
                capture_output=True,
                text=True,
                check=True,
            )
            remote_url = result.stdout.strip()
        except subprocess.CalledProcessError:
            console.print("[red]Error: Could not get remote URL from main _agenttree[/red]")
            sys.exit(1)

        # Clone the repo
        console.print(f"[cyan]Cloning _agenttree from {remote_url}...[/cyan]")
        try:
            subprocess.run(
                ["git", "clone", remote_url, "_agenttree"],
                cwd=cwd,
                check=True,
            )
            console.print(f"[green]✓ Cloned _agenttree[/green]")
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error cloning: {e}[/red]")
            sys.exit(1)

    # Verify/create .env with agent identity
    env_file = cwd / ".env"
    env_content = {}

    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                env_content[key.strip()] = value.strip()

    # Update agent identity
    env_content["AGENT_NUM"] = str(agent_num)
    env_content["PORT"] = str(port)

    # Write back
    with open(env_file, "w") as f:
        for key, value in env_content.items():
            f.write(f"{key}={value}\n")

    console.print(f"[green]✓ Agent identity verified: AGENT_NUM={agent_num}, PORT={port}[/green]")

    # Show summary
    console.print(f"\n[bold]Agent {agent_num} context initialized:[/bold]")
    console.print(f"  _agenttree/ - Issues, skills, templates")
    console.print(f"  .env - AGENT_NUM={agent_num}, PORT={port}")
    console.print(f"\n[dim]Read CLAUDE.md for workflow instructions[/dim]")


@click.command("cleanup")
@click.option(
    "--dry-run", "-n",
    is_flag=True,
    help="Show what would be cleaned up without actually doing it"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Skip confirmation prompts"
)
@click.option(
    "--worktrees/--no-worktrees",
    default=True,
    help="Clean up stale worktrees (default: yes)"
)
@click.option(
    "--branches/--no-branches",
    default=True,
    help="Clean up merged/orphan branches (default: yes)"
)
@click.option(
    "--sessions/--no-sessions",
    default=True,
    help="Clean up orphan tmux sessions (default: yes)"
)
@click.option(
    "--containers/--no-containers",
    default=True,
    help="Clean up orphan containers (default: yes)"
)
@click.option(
    "--ai-review",
    is_flag=True,
    help="Ask controller AI to review edge cases before cleanup"
)
def cleanup_command(
    dry_run: bool,
    force: bool,
    worktrees: bool,
    branches: bool,
    sessions: bool,
    containers: bool,
    ai_review: bool,
) -> None:
    """Clean up dead worktrees, branches, tmux sessions, and containers.

    Identifies and removes stale resources from:

    \b
    - Worktrees: For issues in terminal stages (accepted, not_doing) or
                 backlogged with no uncommitted changes
    - Branches: Local branches that have been merged to main or whose
                issues are in terminal stages
    - Sessions: Tmux sessions for issues that no longer exist or are closed
    - Containers: Running containers for closed issues

    Examples:
        agenttree cleanup                    # Clean everything, prompt for each
        agenttree cleanup --dry-run          # Preview what would be cleaned
        agenttree cleanup --force            # Clean without prompts
        agenttree cleanup --no-branches      # Skip branch cleanup
        agenttree cleanup --ai-review        # Ask controller AI about edge cases
    """
    from agenttree.worktree import list_worktrees, remove_worktree
    from agenttree.tmux import list_sessions, kill_session
    from agenttree.state import get_active_agent

    # Block if in container
    if is_running_in_container():
        console.print("[red]Error: 'cleanup' cannot be run from inside a container[/red]")
        sys.exit(1)

    config = load_config()
    repo_path = Path.cwd()

    # Track what we find
    stale_worktrees: list[dict] = []
    stale_branches: list[str] = []
    stale_sessions: list[str] = []
    stale_containers: list[dict] = []
    edge_cases: list[dict] = []

    # Get all issues for reference
    all_issues = list_issues_func()
    issue_by_id = {i.id: i for i in all_issues}

    console.print("[bold]Scanning for stale resources...[/bold]\n")

    # 1. Find stale worktrees
    if worktrees:
        console.print("[dim]Checking worktrees...[/dim]")
        git_worktrees = list_worktrees(repo_path)

        for wt in git_worktrees:
            wt_path = Path(wt["path"])

            # Skip main repo
            if wt_path == repo_path:
                continue

            # Skip non-issue worktrees
            wt_name = wt_path.name
            if not wt_name.startswith("issue-"):
                continue

            # Extract issue ID from worktree name (issue-XXX-slug)
            parts = wt_name.split("-")
            if len(parts) < 2:
                continue

            issue_id = parts[1]
            issue = issue_by_id.get(issue_id)

            # Check if worktree should be cleaned
            reason = None
            is_edge_case = False

            if not issue:
                reason = "issue not found"
            elif config.is_parking_lot(issue.stage):
                # Parking lot stages may have worktrees cleaned up
                if issue.stage == BACKLOG:
                    # For backlog, keep worktree if there are uncommitted changes
                    status_result = subprocess.run(
                        ["git", "status", "--porcelain"],
                        cwd=wt_path,
                        capture_output=True,
                        text=True,
                    )
                    if not status_result.stdout.strip():
                        reason = "backlogged with no changes"
                    else:
                        is_edge_case = True
                        edge_cases.append({
                            "type": "worktree",
                            "path": str(wt_path),
                            "issue_id": issue_id,
                            "reason": "backlogged but has uncommitted changes",
                        })
                else:
                    # Other parking lots (accepted, not_doing) always clean up
                    reason = f"issue in {issue.stage} stage"

            if reason:
                stale_worktrees.append({
                    "path": str(wt_path),
                    "branch": wt["branch"],
                    "issue_id": issue_id,
                    "reason": reason,
                })

    # 2. Find stale branches
    if branches:
        console.print("[dim]Checking branches...[/dim]")

        # Get all local branches
        result = subprocess.run(
            ["git", "branch", "--list"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        local_branches = [b.strip().lstrip("* ") for b in result.stdout.strip().split("\n") if b.strip()]

        # Get merged branches
        result = subprocess.run(
            ["git", "branch", "--merged", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        merged_branches = {b.strip().lstrip("* ") for b in result.stdout.strip().split("\n") if b.strip()}

        for branch in local_branches:
            # Skip main and HEAD
            if branch in ("main", "master", "HEAD"):
                continue

            # Check if it's an issue branch
            branch_issue_id: str | None = None
            if branch.startswith("issue-"):
                # issue-XXX-slug format
                parts = branch.split("-")
                if len(parts) >= 2:
                    branch_issue_id = parts[1]

            reason = None
            if branch in merged_branches and branch != "main":
                reason = "merged to main"
            elif branch_issue_id:
                issue = issue_by_id.get(branch_issue_id)
                if not issue:
                    reason = "issue not found"
                elif config.is_parking_lot(issue.stage) and issue.stage != BACKLOG:
                    # Clean branches for done/abandoned stages, but keep backlog branches
                    reason = f"issue in {issue.stage} stage"

            if reason:
                stale_branches.append(branch)

    # 3. Find stale tmux sessions
    if sessions:
        console.print("[dim]Checking tmux sessions...[/dim]")

        all_sessions_list = list_sessions()
        project_prefix = f"{config.project}-issue-"

        for session in all_sessions_list:
            if not session.name.startswith(project_prefix):
                continue

            # Extract issue ID from session name
            suffix = session.name[len(project_prefix):]
            # Could be just ID or ID-host
            issue_id = suffix.split("-")[0]

            issue = issue_by_id.get(issue_id)
            if not issue:
                stale_sessions.append(session.name)
            elif config.is_parking_lot(issue.stage):
                # Parking lot stages shouldn't have active sessions
                stale_sessions.append(session.name)
            # Active agent check
            elif not get_active_agent(issue_id):
                # No active agent registered but session exists
                edge_cases.append({
                    "type": "session",
                    "name": session.name,
                    "issue_id": issue_id,
                    "reason": "session exists but no active agent registered",
                })

    # 4. Find stale containers (orphans not tracked in state.yaml)
    if containers:
        console.print("[dim]Checking containers...[/dim]")

        from agenttree.container import list_running_containers
        from agenttree.state import list_active_agents

        runtime = get_container_runtime()
        if runtime.runtime:
            try:
                # Get all running containers
                running_containers = list_running_containers()

                # Get container IDs tracked in state.yaml
                tracked_agents = list_active_agents()
                tracked_container_ids = {a.container for a in tracked_agents}

                # Find orphans: running but not tracked
                for container_id in running_containers:
                    if container_id not in tracked_container_ids:
                        stale_containers.append({
                            "name": container_id,
                            "runtime": runtime.runtime,
                            "reason": "running but not tracked in state",
                        })
            except Exception as e:
                console.print(f"[dim]Note: Could not list containers: {e}[/dim]")

    # Print summary
    console.print("\n[bold]Cleanup Summary:[/bold]\n")

    total_items = len(stale_worktrees) + len(stale_branches) + len(stale_sessions) + len(stale_containers)

    if not total_items and not edge_cases:
        console.print("[green]✓ Nothing to clean up![/green]")
        return

    if stale_worktrees:
        console.print(f"[yellow]Worktrees to remove ({len(stale_worktrees)}):[/yellow]")
        for wt in stale_worktrees:
            console.print(f"  - {wt['path']} ({wt['reason']})")
        console.print()

    if stale_branches:
        console.print(f"[yellow]Branches to delete ({len(stale_branches)}):[/yellow]")
        for branch in stale_branches:
            console.print(f"  - {branch}")
        console.print()

    if stale_sessions:
        console.print(f"[yellow]Tmux sessions to kill ({len(stale_sessions)}):[/yellow]")
        for session_name in stale_sessions:
            console.print(f"  - {session_name}")
        console.print()

    if stale_containers:
        console.print(f"[yellow]Containers to stop ({len(stale_containers)}):[/yellow]")
        for container in stale_containers:
            console.print(f"  - {container['name']} ({container['runtime']})")
        console.print()

    if edge_cases:
        console.print(f"[cyan]Edge cases requiring review ({len(edge_cases)}):[/cyan]")
        for case in edge_cases:
            console.print(f"  - [{case['type']}] {case.get('path') or case.get('name')}: {case['reason']}")
        console.print()

    # AI review for edge cases
    if ai_review and edge_cases:
        console.print("[bold]Asking controller AI to review edge cases...[/bold]")
        _cleanup_ai_review(edge_cases, config)

    if dry_run:
        console.print("[dim]Dry run - no changes made[/dim]")
        return

    # Confirm cleanup
    if not force:
        if not click.confirm(f"\nProceed with cleanup of {total_items} items?"):
            console.print("[dim]Aborted[/dim]")
            return

    # Perform cleanup
    console.print("\n[bold]Cleaning up...[/bold]\n")
    cleaned_count = 0

    # Remove worktrees
    for wt in stale_worktrees:
        try:
            remove_worktree(repo_path, Path(wt["path"]))
            console.print(f"[green]✓ Removed worktree: {wt['path']}[/green]")
            cleaned_count += 1
        except Exception as e:
            console.print(f"[red]✗ Failed to remove worktree {wt['path']}: {e}[/red]")

    # Delete branches
    for branch in stale_branches:
        try:
            subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=repo_path,
                check=True,
                capture_output=True,
            )
            console.print(f"[green]✓ Deleted branch: {branch}[/green]")
            cleaned_count += 1
        except subprocess.CalledProcessError as e:
            console.print(f"[red]✗ Failed to delete branch {branch}: {e}[/red]")

    # Kill tmux sessions
    for session_name in stale_sessions:
        try:
            kill_session(session_name)
            console.print(f"[green]✓ Killed session: {session_name}[/green]")
            cleaned_count += 1
        except Exception as e:
            console.print(f"[red]✗ Failed to kill session {session_name}: {e}[/red]")

    # Stop containers
    for container in stale_containers:
        try:
            runtime = get_container_runtime()
            if not runtime.runtime:
                console.print(f"[yellow]✗ No container runtime to stop: {container['name']}[/yellow]")
                continue
            if runtime.runtime == "container":
                subprocess.run(
                    ["container", "stop", container["name"]],
                    check=True,
                    capture_output=True,
                )
            else:
                subprocess.run(
                    [runtime.runtime, "stop", container["name"]],
                    check=True,
                    capture_output=True,
                )
            console.print(f"[green]✓ Stopped container: {container['name']}[/green]")
            cleaned_count += 1
        except subprocess.CalledProcessError as e:
            console.print(f"[red]✗ Failed to stop container {container['name']}: {e}[/red]")

    console.print(f"\n[green]✓ Cleaned up {cleaned_count} items[/green]")


def _cleanup_ai_review(edge_cases: list[dict], config: Config) -> None:
    """Ask the controller AI to review cleanup edge cases.

    Args:
        edge_cases: List of edge case dictionaries
        config: AgentTree configuration
    """
    from agenttree.tmux import session_exists, send_keys

    controller_session = f"{config.project}-controller"

    if not session_exists(controller_session):
        console.print("[yellow]Controller agent not running - skipping AI review[/yellow]")
        console.print("[dim]Start the controller with: agenttree start --controller[/dim]")
        return

    # Format the edge cases for the AI
    edge_case_text = "\n".join([
        f"- [{c['type']}] {c.get('path') or c.get('name')}: {c['reason']}"
        for c in edge_cases
    ])

    prompt = f"""I'm running `agenttree cleanup` and found these edge cases that need review:

{edge_case_text}

For each edge case, please tell me:
1. Should it be cleaned up? (yes/no)
2. Why?
3. Any risks or considerations?

Be concise - just a few lines per case."""

    console.print("[dim]Sending to controller for review...[/dim]")
    send_keys(controller_session, prompt + "\n")
    console.print(f"[cyan]Sent edge cases to controller. Check tmux session '{controller_session}' for response.[/cyan]")


@click.command("tui")
def tui_command() -> None:
    """Launch the Terminal User Interface for issue management.

    A keyboard-driven interface for managing issues:
    - Arrow keys to navigate
    - Enter to select
    - a = Advance stage
    - r = Reject (send back)
    - s = Start agent
    - / = Filter
    - R = Refresh
    - q = Quit
    """
    try:
        from agenttree.tui import TUIApp
    except ImportError:
        console.print("[red]Error: TUI dependencies not installed[/red]")
        console.print("Install with: pip install agenttree[tui]")
        sys.exit(1)

    app = TUIApp()
    app.run()
