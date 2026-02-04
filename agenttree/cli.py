"""CLI for AgentTree."""

import subprocess
import sys
from pathlib import Path
from typing import Optional
import click
from rich.console import Console
from rich.table import Table

from agenttree.config import load_config, Config
from agenttree.worktree import WorktreeManager
from agenttree.tmux import TmuxManager, save_tmux_history_to_file
from agenttree.github import ensure_gh_cli
from agenttree.container import get_container_runtime
from agenttree.dependencies import check_all_dependencies, print_dependency_report
from agenttree.agents_repo import AgentsRepository
from agenttree.cli_docs import create_rfc, create_investigation, create_note, complete, resume
from agenttree.issues import (
    Priority,
    HUMAN_REVIEW_STAGES,
    create_issue as create_issue_func,
    list_issues as list_issues_func,
    get_issue as get_issue_func,
    get_issue_dir,
    get_issue_context,
    get_next_stage,
    update_issue_stage,
    update_issue_metadata,
    load_skill,
    load_persona,
    # Session management
    create_session,
    get_session,
    is_restart,
    mark_session_oriented,
    update_session_stage,
    delete_session,
    # Stage constants (strings)
    BACKLOG,
    DEFINE,
    PLAN_ASSESS,
    PLAN_REVISE,
    ACCEPTED,
    NOT_DOING,
)
from agenttree.hooks import (
    execute_exit_hooks,
    execute_enter_hooks,
    ValidationError,
    StageRedirect,
    is_running_in_container,
    get_current_role,
    can_agent_operate_in_stage,
)
from agenttree.preflight import run_preflight

console = Console()


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """AgentTree: Multi-Agent Development Framework

    Orchestrate multiple AI coding agents across git worktrees.
    """
    pass


@main.command()
@click.option(
    "--worktrees-dir",
    type=click.Path(),
    help="Directory for worktrees (default: .worktrees/)",
)
@click.option("--project", help="Project name for tmux sessions")
def init(worktrees_dir: Optional[str], project: Optional[str]) -> None:
    """Initialize AgentTree in the current repository."""
    import importlib.resources

    repo_path = Path.cwd()

    # Batch check all dependencies upfront
    success, results = check_all_dependencies(repo_path)
    print_dependency_report(results)
    if not success:
        sys.exit(1)

    config_file = repo_path / ".agenttree.yaml"

    if config_file.exists():
        console.print("[yellow]Warning: .agenttree.yaml already exists[/yellow]")
        if not click.confirm("Overwrite?"):
            return

    # Determine project name
    if not project:
        project = repo_path.name

    # Copy default config template and substitute project name
    template_path = importlib.resources.files("agenttree.templates").joinpath("default.agenttree.yaml")
    config_content = template_path.read_text()
    config_content = config_content.replace("{{PROJECT_NAME}}", project)
    if worktrees_dir:
        config_content = config_content.replace("worktrees_dir: .worktrees", f"worktrees_dir: {worktrees_dir}")
    config_file.write_text(config_content)
    console.print(f"[green]✓ Created {config_file}[/green]")

    # Initialize agents repository (from template - includes all scripts/skills/templates)
    # Note: gh CLI and auth were already validated in check_all_dependencies()
    console.print("\n[cyan]Initializing agents repository from template...[/cyan]")
    try:
        agents_repo = AgentsRepository(repo_path)
        agents_repo.ensure_repo()
        console.print("[green]✓ _agenttree/ repository created[/green]")
    except RuntimeError as e:
        console.print(f"[yellow]Warning: Could not create agents repository:[/yellow]")
        console.print(f"  {e}")
        console.print("\n[yellow]You can create it later by running 'agenttree init' again[/yellow]")

    # Print AI-friendly next steps (users typically run init from Claude/Cursor)
    console.print("\n[bold green]✓ AgentTree initialized![/bold green]")
    console.print("\n[bold cyan]Next steps:[/bold cyan]")
    console.print("""
```bash
# 1. Create a test issue to verify setup
agenttree issue create "Verify setup" --problem "Run the app and fix any setup issues in _agenttree/scripts/worktree-setup.sh. Commit your fixes so future agents benefit."

# 2. Start an agent on it
agenttree start 001

# 3. Once working, create real issues and start agents
agenttree issue create "Your first real issue" --problem "Description of what needs to be done..."
agenttree start 002
```
""")
    console.print("[dim]Tip: The output above is designed for AI agents - if you're using Claude Code or Cursor,[/dim]")
    console.print("[dim]they can execute these commands directly.[/dim]")


@main.command()
def upgrade() -> None:
    """Upgrade _agenttree/ with latest templates from upstream.
    
    Pulls updates from davefowler/agenttree-template and merges them
    into your local _agenttree/ repository. Your customizations are
    preserved through standard git merge.
    """
    repo_path = Path.cwd()
    agents_path = repo_path / "_agenttree"
    
    if not agents_path.exists():
        console.print("[red]Error: _agenttree/ directory not found.[/red]")
        console.print("Run 'agenttree init' first.")
        return
    
    if not (agents_path / ".git").exists():
        console.print("[red]Error: _agenttree/ is not a git repository.[/red]")
        return
    
    # Check if upstream remote exists
    result = subprocess.run(
        ["git", "-C", str(agents_path), "remote", "get-url", "upstream"],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        console.print("[yellow]No upstream remote found. Adding it now...[/yellow]")
        subprocess.run(
            ["git", "-C", str(agents_path), "remote", "add", "upstream",
             "https://github.com/davefowler/agenttree-template.git"],
            check=True,
        )
    
    console.print("[cyan]Fetching updates from upstream template...[/cyan]")
    fetch_result = subprocess.run(
        ["git", "-C", str(agents_path), "fetch", "upstream"],
        capture_output=True,
        text=True,
    )
    
    if fetch_result.returncode != 0:
        console.print(f"[red]Failed to fetch upstream: {fetch_result.stderr}[/red]")
        return
    
    # Check if there are any changes to merge
    diff_result = subprocess.run(
        ["git", "-C", str(agents_path), "rev-list", "HEAD..upstream/main", "--count"],
        capture_output=True,
        text=True,
    )
    
    if diff_result.stdout.strip() == "0":
        console.print("[green]✓ Already up to date![/green]")
        return
    
    commits_behind = diff_result.stdout.strip()
    console.print(f"[cyan]Merging {commits_behind} new commit(s) from upstream...[/cyan]")
    
    # Try to merge
    merge_result = subprocess.run(
        ["git", "-C", str(agents_path), "merge", "upstream/main", "--no-edit"],
        capture_output=True,
        text=True,
    )
    
    if merge_result.returncode != 0:
        if "conflict" in merge_result.stdout.lower() or "conflict" in merge_result.stderr.lower():
            console.print("[yellow]Merge conflicts detected![/yellow]")
            console.print("\nResolve conflicts manually:")
            console.print(f"  cd {agents_path}")
            console.print("  # Edit conflicting files")
            console.print("  git add .")
            console.print("  git commit")
            console.print("  git push origin main")
        else:
            console.print(f"[red]Merge failed: {merge_result.stderr}[/red]")
        return
    
    console.print("[green]✓ Merged successfully![/green]")
    
    # Push to origin
    console.print("[dim]Pushing to your _agenttree repo...[/dim]")
    push_result = subprocess.run(
        ["git", "-C", str(agents_path), "push", "origin", "main"],
        capture_output=True,
        text=True,
    )
    
    if push_result.returncode == 0:
        console.print("[green]✓ Upgrade complete![/green]")
    else:
        console.print(f"[yellow]Warning: Could not push changes: {push_result.stderr}[/yellow]")
        console.print("Changes are committed locally. Push manually with:")
        console.print(f"  cd {agents_path} && git push origin main")


@main.command()
@click.argument("agent_numbers", nargs=-1, type=int, required=True)
def setup(agent_numbers: tuple) -> None:
    """Set up worktrees for agents."""
    repo_path = Path.cwd()
    config = load_config(repo_path)

    manager = WorktreeManager(repo_path, config)

    # Check if custom setup script exists
    setup_script = repo_path / "_agenttree" / "scripts" / "worktree-setup.sh"
    has_custom_setup = setup_script.exists()

    if has_custom_setup:
        console.print(f"[cyan]Using custom setup script: {setup_script}[/cyan]\n")

    for agent_num in agent_numbers:
        try:
            console.print(f"[bold]Setting up agent-{agent_num}...[/bold]")
            worktree_path = manager.setup_agent(agent_num)
            port = config.get_port_for_agent(agent_num)

            # Run custom setup script if it exists
            if has_custom_setup:
                console.print(f"[dim]Running worktree-setup.sh...[/dim]")
                result = subprocess.run(
                    [str(setup_script), str(worktree_path), str(agent_num), str(port)],
                    cwd=repo_path,
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    if result.stdout:
                        console.print(result.stdout.strip())
                else:
                    console.print(f"[yellow]Warning: Setup script failed:[/yellow]")
                    console.print(result.stderr)
            else:
                # Fallback: basic .env copy (legacy behavior)
                console.print("[dim]No custom setup script found, using default behavior[/dim]")
                env_file = worktree_path / ".env"

                if (repo_path / ".env").exists():
                    import shutil
                    shutil.copy(repo_path / ".env", env_file)

                # Update or add PORT
                if env_file.exists():
                    with open(env_file, "r") as f:
                        lines = f.readlines()

                    with open(env_file, "w") as f:
                        port_written = False
                        for line in lines:
                            if line.startswith("PORT="):
                                f.write(f"PORT={port}\n")
                                port_written = True
                            else:
                                f.write(line)

                        if not port_written:
                            f.write(f"PORT={port}\n")
                else:
                    with open(env_file, "w") as f:
                        f.write(f"PORT={port}\n")

            console.print(f"[green]✓ Agent {agent_num} ready at {worktree_path}[/green]")
        except Exception as e:
            console.print(f"[red]✗ Failed to set up agent {agent_num}: {e}[/red]")


@main.command()
def preflight() -> None:
    """Run environment preflight checks.

    Validates that the environment is properly set up for agent work:
    - Python version meets minimum requirement
    - Dependencies are installed
    - Git is available and working
    - agenttree CLI is accessible
    - Test runner (pytest) is available
    """
    console.print("[bold]Running preflight checks...[/bold]\n")

    results = run_preflight()
    all_passed = True

    for result in results:
        if result.passed:
            console.print(f"[green]✓[/green] {result.name}: {result.message}")
        else:
            console.print(f"[red]✗[/red] {result.name}: {result.message}")
            if result.fix_hint:
                console.print(f"  [dim]Hint: {result.fix_hint}[/dim]")
            all_passed = False

    console.print("")

    if all_passed:
        console.print("[green]✓ All preflight checks passed[/green]")
        sys.exit(0)
    else:
        console.print("[red]✗ Some preflight checks failed[/red]")
        sys.exit(1)


def _start_manager(
    tool: Optional[str],
    force: bool,
    config: "Config",
    repo_path: Path,
) -> None:
    """Start the manager agent (agent 0).

    The manager runs on the host (not in a container) and orchestrates
    work across all issues. It uses the main branch.
    """
    from agenttree.tmux import session_exists

    tmux_manager = TmuxManager(config)
    session_name = f"{config.project}-manager-000"

    # Check if manager already running
    if session_exists(session_name) and not force:
        console.print("[yellow]Manager already running[/yellow]")
        console.print(f"\nUse --force to restart, or attach with:")
        console.print(f"  agenttree attach 0")
        sys.exit(1)

    tool_name = tool or config.default_tool
    console.print(f"[green]Starting manager agent...[/green]")
    console.print(f"[dim]Tool: {tool_name}[/dim]")
    console.print(f"[dim]Session: {session_name}[/dim]")

    # Start manager on host (not in container)
    tmux_manager.start_manager(
        session_name=session_name,
        repo_path=repo_path,
        tool_name=tool_name,
    )

    console.print(f"\n[bold]Manager ready[/bold]")
    console.print(f"\n[dim]Commands:[/dim]")
    console.print(f"  agenttree attach 0")
    console.print(f"  agenttree send 0 'message'")
    console.print(f"  agenttree kill 0")


@main.command(name="start")
@click.argument("issue_id", type=str)
@click.option("--tool", help="AI tool to use (default: from config)")
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.option("--force", is_flag=True, help="Force start even if agent already exists")
@click.option("--skip-preflight", is_flag=True, help="Skip preflight environment checks")
def start_agent(
    issue_id: str,
    tool: Optional[str],
    role: str,
    force: bool,
    skip_preflight: bool,
) -> None:
    """Start an agent for an issue (creates container + worktree).

    ISSUE_ID is the issue number (e.g., "23" or "023").

    This creates a dedicated agent for the issue with:
    - A new worktree (issue-023-slug/)
    - A new container (agenttree-{role}-023)
    - A tmux session for interaction

    The agent is automatically cleaned up when the issue is accepted.

    Use --role to start a non-default agent (e.g., --role reviewer for code review).
    """
    from agenttree.state import (
        get_active_agent,
        get_port_for_issue,
        create_agent_for_issue,
        get_issue_names,
    )
    from agenttree.worktree import create_worktree, update_worktree_with_main

    repo_path = Path.cwd()
    config = load_config(repo_path)

    # Run preflight checks unless skipped
    if not skip_preflight:
        console.print("[dim]Running preflight checks...[/dim]")
        results = run_preflight()
        failed = [r for r in results if not r.passed]
        if failed:
            console.print("[red]Preflight checks failed:[/red]")
            for result in failed:
                console.print(f"  [red]✗[/red] {result.name}: {result.message}")
                if result.fix_hint:
                    console.print(f"    [dim]Hint: {result.fix_hint}[/dim]")
            console.print("\n[yellow]Use --skip-preflight to bypass these checks[/yellow]")
            sys.exit(1)
        console.print("[green]✓ Preflight checks passed[/green]\n")

    # Normalize issue ID (strip leading zeros for lookup, keep for display)
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Special handling for manager (agent 0)
    if issue_id_normalized == "0":
        _start_manager(tool, force, config, repo_path)
        return

    # Load issue from local _agenttree/issues/
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Error: Issue #{issue_id} not found in _agenttree/issues/[/red]")
        console.print(f"[yellow]Create it with: agenttree issue create 'title'[/yellow]")
        sys.exit(1)

    # If issue is in backlog, move it to define stage first
    if issue.stage == "backlog":
        from agenttree.issues import update_issue_stage
        console.print(f"[cyan]Moving issue from backlog to define...[/cyan]")
        update_issue_stage(issue.id, "define")
        issue.stage = "define"  # Update local reference

    # Check if issue already has an active agent for this host
    existing_agent = get_active_agent(issue.id, role)
    if existing_agent and not force:
        console.print(f"[yellow]Issue #{issue.id} already has an active {role} agent[/yellow]")
        console.print(f"  Container: {existing_agent.container}")
        console.print(f"  Port: {existing_agent.port}")
        console.print(f"\nUse --force to replace it, or attach with:")
        console.print(f"  agenttree attach {issue.id}" + (f" --role {role}" if role != "developer" else ""))
        sys.exit(1)

    # Initialize managers
    tmux_manager = TmuxManager(config)
    agents_repo = AgentsRepository(repo_path)

    # Ensure agents repo exists
    agents_repo.ensure_repo()

    # Get names for this issue and host
    names = get_issue_names(issue.id, issue.slug, config.project, role)

    # Create worktree for issue
    worktree_path = config.get_issue_worktree_path(issue.id, issue.slug)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    has_merge_conflicts = False
    is_restart = False
    if worktree_path.exists():
        # Worktree exists - this is a restart scenario
        is_restart = True
        # Update with latest main to get newest CLI code while preserving agent's work
        console.print(f"[cyan]Restarting: Rebasing worktree onto latest main...[/cyan]")
        update_success = update_worktree_with_main(worktree_path)
        if update_success:
            console.print(f"[green]✓ Worktree rebased successfully[/green]")
        else:
            has_merge_conflicts = True
            console.print(f"[yellow]⚠ Merge conflicts detected - agent will need to resolve[/yellow]")
    else:
        # No worktree - check if branch exists (agent worked on this before but worktree was removed)
        branch_exists = subprocess.run(
            ["git", "rev-parse", "--verify", names["branch"]],
            cwd=repo_path,
            capture_output=True,
        ).returncode == 0

        if branch_exists:
            # Branch exists - create worktree from it, then update with main
            is_restart = True
            console.print(f"[dim]Restarting from existing branch: {names['branch']}[/dim]")
            create_worktree(repo_path, worktree_path, names["branch"])
            console.print(f"[cyan]Rebasing onto latest main...[/cyan]")
            update_success = update_worktree_with_main(worktree_path)
            if update_success:
                console.print(f"[green]✓ Worktree rebased successfully[/green]")
            else:
                has_merge_conflicts = True
                console.print(f"[yellow]⚠ Merge conflicts detected - agent will need to resolve[/yellow]")
        else:
            # Fresh start - create new worktree from main
            console.print(f"[dim]Creating worktree: {worktree_path.name}[/dim]")
            create_worktree(repo_path, worktree_path, names["branch"])

    # Get deterministic port from issue number
    base_port = int(config.port_range.split("-")[0])
    port = get_port_for_issue(issue.id, base_port=base_port)
    console.print(f"[dim]Using port: {port} (derived from issue #{issue.id})[/dim]")

    # Register agent in state
    agent = create_agent_for_issue(
        issue_id=issue.id,
        slug=issue.slug,
        worktree_path=worktree_path,
        port=port,
        project=config.project,
        role=role,
    )

    # Save branch and worktree info to issue metadata
    update_issue_metadata(issue.id, branch=names["branch"], worktree_dir=str(worktree_path))

    role_label = f" ({role})" if role != "developer" else ""
    console.print(f"[green]✓ Starting agent{role_label} for issue #{issue.id}: {issue.title}[/green]")

    # Create session for restart detection
    create_session(issue.id)

    # Start agent in tmux (always in container)
    tool_name = tool or config.default_tool
    # Resolve model from stage config (substage → stage → default)
    model_name = config.model_for(issue.stage, issue.substage)
    runtime = get_container_runtime()

    if not runtime.is_available():
        console.print(f"[red]Error: No container runtime available[/red]")
        console.print(f"Recommendation: {runtime.get_recommended_action()}")
        sys.exit(1)

    console.print(f"[dim]Container runtime: {runtime.get_runtime_name()}[/dim]")
    console.print(f"[dim]Model: {model_name}[/dim]")

    # Use the host parameter (which was either explicitly set or defaults to "agent")
    start_success = tmux_manager.start_issue_agent_in_container(
        issue_id=issue.id,
        session_name=agent.tmux_session,
        worktree_path=worktree_path,
        tool_name=tool_name,
        container_runtime=runtime,
        model=model_name,
        role=role,
        has_merge_conflicts=has_merge_conflicts,
        is_restart=is_restart,
    )

    if not start_success:
        # Startup failed - clean up state and exit
        from agenttree.state import unregister_agent
        unregister_agent(issue.id, role)
        console.print(f"[red]Error: Agent failed to start (Claude prompt not detected within timeout)[/red]")
        console.print(f"[dim]State has been cleaned up. Try running 'agenttree start {issue.id}' again.[/dim]")
        sys.exit(1)

    console.print(f"[green]✓ Started {tool_name} in container[/green]")

    # For Apple Containers, look up the UUID and store it for cleanup
    if runtime.get_runtime_name() == "container":
        import time
        from agenttree.container import find_container_by_worktree
        from agenttree.state import update_agent_container_id

        # Wait for container to start, then find its UUID
        for _ in range(10):  # Try for up to 5 seconds
            time.sleep(0.5)
            container_uuid = find_container_by_worktree(worktree_path)
            if container_uuid:
                update_agent_container_id(issue.id, container_uuid, role)
                console.print(f"[dim]Container UUID: {container_uuid[:12]}...[/dim]")
                break
        else:
            console.print(f"[yellow]Warning: Could not find container UUID for cleanup tracking[/yellow]")

    console.print(f"\n[bold]Agent{role_label} ready for issue #{issue.id}[/bold]")
    console.print(f"  Container: {agent.container}")
    console.print(f"  Port: {agent.port}")
    console.print(f"  Role: {role}")
    console.print(f"\n[dim]Commands:[/dim]")
    role_flag = f" --role {role}" if role != "developer" else ""
    console.print(f"  agenttree attach {issue.id}{role_flag}")
    console.print(f"  agenttree send {issue.id}{role_flag} 'message'")
    console.print(f"  agenttree agents")


@main.command("agents")
def agents_status() -> None:
    """Show status of all active issue agents."""
    from agenttree.state import list_active_agents

    config = load_config()
    tmux_manager = TmuxManager(config)

    agents = list_active_agents()

    if not agents:
        console.print("[dim]No active agents[/dim]")
        console.print("\nStart an agent with:")
        console.print("  agenttree start <issue_id>")
        return

    table = Table(title="Active Agents")
    table.add_column("ID", style="bold cyan")
    table.add_column("Host", style="blue")
    table.add_column("Title", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Port", style="green")
    table.add_column("Branch", style="yellow")

    for agent in agents:
        # Check if tmux session is running
        is_running = tmux_manager.is_issue_running(agent.tmux_session)

        # Get issue info
        issue = get_issue_func(agent.issue_id)
        issue_title = issue.title[:30] if issue else "Unknown"

        # Determine status
        if is_running:
            status_str = "🟢 Running"
        else:
            status_str = "⚪ Stopped"

        table.add_row(
            agent.issue_id,
            agent.role,
            issue_title,
            status_str,
            str(agent.port),
            agent.branch[:20],
        )

    console.print(table)
    console.print(f"\n[dim]Commands (use ID from table above, add --role if not 'developer'):[/dim]")
    console.print(f"  agenttree attach <id> [--role <role>]")
    console.print(f"  agenttree send <id> [--role <role>] 'message'")
    console.print(f"  agenttree stop <id> [--role <role>]")


@main.command()
@click.argument("name", default="default", required=False)
@click.option("--list", "-l", "list_sandboxes", is_flag=True, help="List active sandboxes")
@click.option("--kill", "-k", is_flag=True, help="Kill the sandbox")
@click.option("--tool", help="AI tool to use (default: from config)")
@click.option("--git", "-g", "share_git", is_flag=True, help="Share git credentials (~/.ssh, ~/.gitconfig)")
def sandbox(name: str, list_sandboxes: bool, kill: bool, tool: Optional[str], share_git: bool) -> None:
    """Start a sandbox container for ad-hoc work.

    NAME is an optional sandbox name (default: "default").

    Examples:
        agenttree sandbox              # Start default sandbox
        agenttree sandbox experiments  # Start named sandbox
        agenttree sandbox --git        # Start with git credentials
        agenttree sandbox --list       # List active sandboxes
        agenttree sandbox --kill       # Kill default sandbox
        agenttree sandbox exp --kill   # Kill named sandbox
    """
    from agenttree.container import get_container_runtime
    from agenttree.tmux import (
        create_session,
        kill_session,
        session_exists,
        attach_session,
        list_sessions,
        wait_for_prompt,
        send_keys,
    )

    config = load_config()
    project = config.project

    # Sandbox session naming convention: {project}-sandbox-{name}
    def get_sandbox_session_name(sandbox_name: str) -> str:
        return f"{project}-sandbox-{sandbox_name}"

    # List sandboxes
    if list_sandboxes:
        sessions = list_sessions()
        sandbox_prefix = f"{project}-sandbox-"
        sandbox_sessions = [s for s in sessions if s.name.startswith(sandbox_prefix)]

        if not sandbox_sessions:
            console.print("[dim]No active sandboxes[/dim]")
            console.print("\nStart one with:")
            console.print("  agenttree sandbox [name]")
            return

        table = Table(title="Active Sandboxes")
        table.add_column("Name", style="bold cyan")
        table.add_column("Session", style="dim")

        for session in sandbox_sessions:
            sandbox_name = session.name[len(sandbox_prefix):]
            table.add_row(sandbox_name, session.name)

        console.print(table)
        console.print(f"\n[dim]Commands:[/dim]")
        console.print(f"  agenttree sandbox <name>        # Attach to sandbox")
        console.print(f"  agenttree sandbox <name> --kill # Kill sandbox")
        return

    session_name = get_sandbox_session_name(name)

    # Kill sandbox
    if kill:
        if session_exists(session_name):
            kill_session(session_name)
            console.print(f"[green]✓ Killed sandbox '{name}'[/green]")
        else:
            console.print(f"[yellow]Sandbox '{name}' not running[/yellow]")
        return

    # Check if sandbox already exists - if so, attach to it
    if session_exists(session_name):
        console.print(f"[cyan]Attaching to existing sandbox '{name}' (Ctrl+B, D to detach)...[/cyan]")
        attach_session(session_name)
        return

    # Start new sandbox
    runtime = get_container_runtime()
    if not runtime.is_available():
        console.print(f"[red]Error: No container runtime available[/red]")
        console.print(f"Recommendation: {runtime.get_recommended_action()}")
        sys.exit(1)

    console.print(f"[cyan]Starting sandbox '{name}'...[/cyan]")
    console.print(f"[dim]Container runtime: {runtime.get_runtime_name()}[/dim]")

    # Ensure container system is running
    runtime.ensure_system_running()

    # Build container command using current directory (main repo)
    repo_path = Path.cwd()
    tool_name = tool or config.default_tool
    home = Path.home()

    # Build additional args for git credential sharing
    additional_args: list[str] = []
    if share_git:
        ssh_dir = home / ".ssh"
        gitconfig = home / ".gitconfig"
        if ssh_dir.exists():
            additional_args.extend(["-v", f"{ssh_dir}:/home/agent/.ssh:ro"])
            console.print(f"[dim]Sharing ~/.ssh (read-only)[/dim]")
        if gitconfig.exists():
            additional_args.extend(["-v", f"{gitconfig}:/home/agent/.gitconfig:ro"])
            console.print(f"[dim]Sharing ~/.gitconfig (read-only)[/dim]")

    container_cmd = runtime.build_run_command(
        worktree_path=repo_path,
        ai_tool=tool_name,
        dangerous=True,
        model=config.default_model,
        additional_args=additional_args if additional_args else None,
    )
    container_cmd_str = " ".join(container_cmd)

    # Create tmux session running the container
    create_session(session_name, repo_path, container_cmd_str)
    console.print(f"[green]✓ Started sandbox '{name}'[/green]")

    # Wait for prompt and send a friendly message
    if wait_for_prompt(session_name, prompt_char="❯", timeout=30.0):
        send_keys(session_name, "echo 'Sandbox ready! Working in main repo.'")

    console.print(f"\n[bold]Sandbox '{name}' ready[/bold]")
    console.print(f"\n[dim]Commands:[/dim]")
    console.print(f"  agenttree sandbox {name}        # Attach")
    console.print(f"  agenttree sandbox {name} --kill # Stop")
    console.print(f"  agenttree sandbox --list        # List all")

    # Auto-attach
    console.print(f"\n[cyan]Attaching... (Ctrl+B, D to detach)[/cyan]")
    attach_session(session_name)


@main.command()
@click.argument("issue_id", type=str)
@click.option("--role", default="developer", help="Agent role (default: developer)")
def attach(issue_id: str, role: str) -> None:
    """Attach to an issue's agent tmux session.

    ISSUE_ID is the issue number (e.g., "23" or "023"), or "0" for manager.
    """
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists, attach_session

    config = load_config()
    tmux_manager = TmuxManager(config)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Special handling for manager (agent 0)
    if issue_id_normalized == "0":
        session_name = f"{config.project}-manager-000"
        if not session_exists(session_name):
            console.print("[red]Error: Manager not running[/red]")
            console.print("[yellow]Start it with: agenttree start 0[/yellow]")
            sys.exit(1)
        console.print("Attaching to manager (Ctrl+B, D to detach)...")
        attach_session(session_name)
        return

    # Get active agent for this issue and role
    agent = get_active_agent(issue_id_normalized, role)
    if not agent:
        # Try with padded ID
        issue = get_issue_func(issue_id_normalized)
        if issue:
            agent = get_active_agent(issue.id, role)

    if not agent:
        role_label = f" ({role})" if role != "developer" else ""
        console.print(f"[red]Error: No active{role_label} agent for issue #{issue_id}[/red]")
        role_flag = f" --role {role}" if role != "developer" else ""
        console.print(f"[yellow]Start one with: agenttree start {issue_id}{role_flag}[/yellow]")
        sys.exit(1)

    try:
        role_label = f" ({agent.role})" if agent.role != "developer" else ""
        console.print(f"Attaching to issue #{agent.issue_id}{role_label} (Ctrl+B, D to detach)...")
        tmux_manager.attach_to_issue(agent.tmux_session)
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@main.command()
@click.argument("issue_id", type=str)
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.option("--lines", "-n", default=50, help="Number of lines to show (default: 50)")
def output(issue_id: str, role: str, lines: int) -> None:
    """Show recent output from an agent's tmux session.

    ISSUE_ID is the issue number (e.g., "23" or "023"), or "0" for manager.

    Examples:
        agenttree output 137        # Show last 50 lines from agent #137
        agenttree output 0          # Show manager output
        agenttree output 137 -n 100 # Show last 100 lines
    """
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists, capture_pane

    config = load_config()

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Special handling for manager (agent 0)
    if issue_id_normalized == "0":
        session_name = f"{config.project}-manager-000"
        if not session_exists(session_name):
            console.print("[red]Error: Manager not running[/red]")
            sys.exit(1)
        output_text = capture_pane(session_name, lines=lines)
        console.print(output_text)
        return

    # Get active agent for this issue and role
    agent = get_active_agent(issue_id_normalized, role)
    if not agent:
        # Try with padded ID
        issue = get_issue_func(issue_id_normalized)
        if issue:
            agent = get_active_agent(issue.id, role)

    if not agent:
        role_label = f" ({role})" if role != "developer" else ""
        console.print(f"[red]Error: No active{role_label} agent for issue #{issue_id}[/red]")
        sys.exit(1)

    if not session_exists(agent.tmux_session):
        console.print(f"[red]Error: Tmux session '{agent.tmux_session}' not found[/red]")
        sys.exit(1)

    output_text = capture_pane(agent.tmux_session, lines=lines)
    console.print(output_text)


@main.command()
@click.argument("issue_id", type=str)
@click.argument("message")
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.option("--interrupt", is_flag=True, help="Send Ctrl+C first to interrupt current task")
def send(issue_id: str, message: str, role: str, interrupt: bool) -> None:
    """Send a message to an issue's agent.

    ISSUE_ID is the issue number (e.g., "23" or "023"), or "0" for manager.

    If the agent is not running, it will be automatically started.

    Use --interrupt to stop the agent's current task (sends Ctrl+C) before sending.
    """
    from agenttree.state import get_active_agent
    from agenttree.tmux import session_exists, send_keys

    config = load_config()
    tmux_manager = TmuxManager(config)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Special handling for manager (agent 0)
    if issue_id_normalized == "0":
        session_name = f"{config.project}-manager-000"
        if not session_exists(session_name):
            console.print("[red]Error: Manager not running[/red]")
            console.print("[yellow]Start it with: agenttree start 0[/yellow]")
            sys.exit(1)
        send_keys(session_name, message, interrupt=interrupt)
        console.print("[green]✓ Sent message to manager[/green]")
        return

    # Get issue to validate it exists
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Error: Issue #{issue_id} not found[/red]")
        sys.exit(1)

    # Use the canonical issue ID
    issue_id_normalized = issue.id

    # Helper to start agent if needed
    def ensure_agent_running() -> bool:
        """Start agent if not running. Returns True if agent is now running."""
        agent = get_active_agent(issue_id_normalized, role)
        if agent and tmux_manager.is_issue_running(agent.tmux_session):
            return True

        # Agent not running - start it
        role_label = f" ({role})" if role != "developer" else ""
        console.print(f"[dim]Agent{role_label} not running, starting...[/dim]")

        role_flag = f" --role {role}" if role != "developer" else ""
        result = subprocess.run(
            ["agenttree", "start", issue_id_normalized] + (["--role", role] if role != "developer" else []) + ["--skip-preflight"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Error: Could not start agent: {result.stderr}[/red]")
            return False

        console.print(f"[green]✓ Started agent{role_label}[/green]")
        return True

    # Ensure agent is running
    if not ensure_agent_running():
        sys.exit(1)

    # Re-fetch agent after potential start
    agent = get_active_agent(issue_id_normalized, role)
    if not agent:
        console.print(f"[red]Error: Agent started but not found in state[/red]")
        sys.exit(1)

    # Send the message
    result = tmux_manager.send_message_to_issue(agent.tmux_session, message, interrupt=interrupt)

    role_label = f" ({agent.role})" if agent.role != "developer" else ""
    if result == "sent":
        console.print(f"[green]✓ Sent message to issue #{agent.issue_id}{role_label}[/green]")
    elif result == "claude_exited":
        # Claude exited - restart and try again
        console.print(f"[yellow]Claude CLI exited, restarting agent...[/yellow]")
        if ensure_agent_running():
            agent = get_active_agent(issue_id_normalized, role)
            if agent:
                result = tmux_manager.send_message_to_issue(agent.tmux_session, message)
                if result == "sent":
                    console.print(f"[green]✓ Sent message to issue #{agent.issue_id}{role_label}[/green]")
                    return
        console.print(f"[red]Error: Could not send message after restart[/red]")
        sys.exit(1)
    elif result == "no_session":
        console.print(f"[red]Error: Tmux session not found[/red]")
        sys.exit(1)
    else:
        console.print(f"[red]Error: Failed to send message[/red]")
        sys.exit(1)


@main.command()
@click.argument("issue_id", type=str)
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.option("--all", "all_roles", is_flag=True, help="Stop all agents for this issue (all roles)")
def stop(issue_id: str, role: str, all_roles: bool) -> None:
    """Stop an issue's agent (kills tmux, stops container, cleans up state).

    ISSUE_ID is the issue number (e.g., "23" or "023"), or "0" for manager.

    Examples:
        agenttree stop 23              # Stop the default agent for issue 23
        agenttree stop 23 --role reviewer  # Stop the review agent
        agenttree stop 23 --all        # Stop all agents for issue 23
    """
    from agenttree.state import stop_agent, stop_all_agents_for_issue, get_active_agent
    from agenttree.tmux import session_exists, kill_session

    config = load_config()

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Special handling for manager (agent 0)
    if issue_id_normalized == "0":
        session_name = f"{config.project}-manager-000"
        if not session_exists(session_name):
            console.print("[yellow]Manager not running[/yellow]")
            return
        kill_session(session_name)
        console.print("[green]✓ Stopped manager[/green]")
        return

    # Stop all agents for this issue if --all flag
    if all_roles:
        count = stop_all_agents_for_issue(issue_id_normalized)
        if count == 0:
            console.print(f"[yellow]No active agents for issue #{issue_id}[/yellow]")
        return

    # Try with normalized ID first, then try getting the issue
    issue = get_issue_func(issue_id_normalized)
    actual_id = issue.id if issue else issue_id_normalized

    # Check if agent exists
    agent = get_active_agent(actual_id, role)
    if not agent:
        role_label = f" ({role})" if role != "developer" else ""
        console.print(f"[red]Error: No active{role_label} agent for issue #{issue_id}[/red]")
        sys.exit(1)

    # Use consolidated stop_agent function
    stop_agent(actual_id, role)


# Alias for backwards compatibility - just invokes stop
@main.command(name="kill", hidden=True)
@click.argument("issue_id", type=str)
@click.option("--role", default="developer", help="Agent role (default: developer)")
@click.pass_context
def kill_alias(ctx: click.Context, issue_id: str, role: str) -> None:
    """Alias for 'stop' command (use 'agenttree stop' instead)."""
    ctx.invoke(stop, issue_id=issue_id, role=role, all_roles=False)


@main.group()
def notes() -> None:
    """Manage agents repository notes and documentation."""
    pass


@notes.command("show")
@click.argument("agent_num", type=int)
def notes_show(agent_num: int) -> None:
    """Show task logs for an agent."""
    repo_path = Path.cwd()
    agents_repo = AgentsRepository(repo_path)

    agent_dir = agents_repo.agents_path / "tasks" / f"agent-{agent_num}"

    if not agent_dir.exists():
        console.print(f"[yellow]No tasks found for agent-{agent_num}[/yellow]")
        return

    task_files = sorted(agent_dir.glob("*.md"), reverse=True)

    if not task_files:
        console.print(f"[yellow]No tasks found for agent-{agent_num}[/yellow]")
        return

    console.print(f"\n[cyan]Tasks for agent-{agent_num}:[/cyan]\n")
    for task_file in task_files:
        console.print(f"  • {task_file.name}")

    console.print(f"\n[dim]View task: cat _agenttree/tasks/agent-{agent_num}/<filename>[/dim]")


@notes.command("search")
@click.argument("query")
def notes_search(query: str) -> None:
    """Search all notes for a query."""
    repo_path = Path.cwd()
    agents_repo = AgentsRepository(repo_path)

    if not agents_repo.agents_path.exists():
        console.print("[yellow]Agents repository not initialized[/yellow]")
        return

    console.print(f"\n[cyan]Searching for '{query}'...[/cyan]\n")

    import subprocess

    # Use ripgrep or grep to search
    try:
        result = subprocess.run(
            ["rg", "-i", query, str(agents_repo.agents_path)],
            capture_output=True,
            text=True,
        )
        if result.stdout:
            console.print(result.stdout)
        else:
            console.print("[yellow]No results found[/yellow]")
    except FileNotFoundError:
        # Fallback to grep
        result = subprocess.run(
            ["grep", "-ri", query, str(agents_repo.agents_path)],
            capture_output=True,
            text=True,
        )
        if result.stdout:
            console.print(result.stdout)
        else:
            console.print("[yellow]No results found[/yellow]")


@notes.command("archive")
@click.argument("agent_num", type=int)
def notes_archive(agent_num: int) -> None:
    """Archive completed tasks for an agent."""
    repo_path = Path.cwd()
    agents_repo = AgentsRepository(repo_path)

    agents_repo.archive_task(agent_num)
    console.print(f"[green]✓ Archived completed task for agent-{agent_num}[/green]")


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8080, type=int, help="Port to bind to")
@click.option("--config", type=click.Path(exists=True), help="Path to config file")
def web(host: str, port: int, config: Optional[str]) -> None:
    """Start the web dashboard for monitoring agents.

    The dashboard provides:
    - Real-time agent status monitoring
    - Live tmux output streaming
    - Task start via web UI
    - Command execution for agents
    """
    from agenttree.web.app import run_server

    console.print(f"[cyan]Starting AgentTree dashboard at http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    config_path = Path(config) if config else None
    run_server(host=host, port=port, config_path=config_path)


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8080, type=int, help="Port to bind to")
def serve(host: str, port: int) -> None:
    """Start the AgentTree server (runs syncs, spawns agents).

    This is the main manager process that:
    - Syncs the _agenttree repo periodically
    - Spawns agents for issues in agent stages
    - Runs hooks for manager stages
    - Provides the web dashboard

    Use 'agenttree start' to run this in a tmux session.
    """
    from agenttree.web.app import run_server

    console.print(f"[cyan]Starting AgentTree server at http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    run_server(host=host, port=port)


@main.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=8080, type=int, help="Port to bind to")
@click.option("--skip-agents", is_flag=True, help="Don't auto-start agents")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed event output")
def run(host: str, port: int, skip_agents: bool, verbose: bool) -> None:
    """Start AgentTree: server + agents for all active issues.

    This is the main entry point that:
    1. Fires the 'startup' event (starts controller and agents)
    2. Starts the web server with heartbeat events

    Use 'agenttree stop-all' to stop everything.

    Events are configured in .agenttree.yaml under the `on:` key:

    \b
    on:
      startup:
        - start_controller
        - auto_start_agents
      heartbeat:
        interval_s: 10
        actions:
          - sync
          - check_ci_status: { min_interval_s: 60 }

    Examples:
        agenttree run                  # Start everything
        agenttree run --skip-agents    # Just start the server
        agenttree run --port 9000      # Use custom port
    """
    from agenttree.events import fire_event, STARTUP
    from agenttree.issues import get_agenttree_path
    from agenttree.web.app import run_server

    repo_path = Path.cwd()
    agents_dir = get_agenttree_path()

    if not skip_agents:
        # Fire startup event (runs start_controller, auto_start_agents, etc.)
        console.print("[cyan]Firing startup event...[/cyan]")
        results = fire_event(STARTUP, agents_dir, verbose=verbose)
        
        if results["errors"]:
            for error in results["errors"]:
                console.print(f"[yellow]Warning: {error}[/yellow]")
        
        console.print(f"[green]✓ Startup complete ({results['actions_run']} actions run)[/green]")

    # Start the web server (which handles heartbeat events)
    console.print(f"\n[cyan]Starting AgentTree server at http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    run_server(host=host, port=port)


@main.command("stop-all")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed event output")
def stop_all(verbose: bool) -> None:
    """Stop all agents (opposite of 'agenttree run').

    This fires the 'shutdown' event which:
    1. Syncs the _agenttree repository
    2. Stops all running issue agents
    3. Stops the manager agent (agent 0)

    Events are configured in .agenttree.yaml under the `on:` key:

    \b
    on:
      shutdown:
        - sync
        - stop_all_agents

    Use 'agenttree run' to start everything again.

    Examples:
        agenttree stop-all            # Stop all agents
        agenttree stop-all -v         # Verbose output
    """
    from agenttree.events import fire_event, SHUTDOWN
    from agenttree.issues import get_agenttree_path
    from agenttree.tmux import session_exists, kill_session

    agents_dir = get_agenttree_path()
    config = load_config()

    # Fire shutdown event (runs sync, stop_all_agents, etc.)
    console.print("[cyan]Firing shutdown event...[/cyan]")
    results = fire_event(SHUTDOWN, agents_dir, verbose=verbose)
    
    if results["errors"]:
        for error in results["errors"]:
            console.print(f"[yellow]Warning: {error}[/yellow]")
    
    # Also stop the manager agent (not stopped by stop_all_agents)
    manager_session = f"{config.project}-manager-000"
    if session_exists(manager_session):
        console.print(f"[cyan]Stopping manager agent...[/cyan]")
        kill_session(manager_session)
        console.print(f"[green]✓ Stopped manager[/green]")

    # Stop the web server
    import subprocess
    port = config.port_range.split("-")[0] if hasattr(config, "port_range") else "8080"
    try:
        # Find process on port 8080 (default web server port)
        result = subprocess.run(
            ["lsof", "-ti", ":8080"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = result.stdout.strip().split("\n")
            for pid in pids:
                if pid:
                    subprocess.run(["kill", pid], capture_output=True)
            console.print(f"[green]✓ Stopped web server[/green]")
    except Exception:
        pass  # Web server may not be running

    console.print(f"\n[bold green]✓ Shutdown complete ({results['actions_run']} actions run)[/bold green]")


# manager-start and manager-stop commands removed
# Manager is now agent 0 - use: agenttree start 0, agenttree kill 0


@main.command()
@click.option("--threshold", "-t", default=None, type=int, help="Override stall threshold (minutes)")
def stalls(threshold: int | None) -> None:
    """List agents that appear stalled (in same stage too long).

    Detects agents that have been in a non-review stage for longer than
    the configured threshold (default 20 minutes) without advancing.

    Examples:
        agenttree stalls              # Check for stalled agents
        agenttree stalls -t 30        # Use 30-minute threshold
    """
    from agenttree.manager_agent import get_stalled_agents

    config = load_config()
    agents_dir = Path.cwd() / "_agenttree"

    # Use config threshold or override
    threshold_min = threshold if threshold is not None else config.manager.stall_threshold_min

    stalled = get_stalled_agents(agents_dir, threshold_min=threshold_min)

    if not stalled:
        console.print(f"[green]No stalled agents detected[/green] (threshold: {threshold_min} min)")
        return

    console.print(f"[yellow]Found {len(stalled)} stalled agent(s):[/yellow]\n")

    for agent in stalled:
        console.print(f"  [bold]Issue #{agent['issue_id']}[/bold]: {agent['title']}")
        console.print(f"    Stage: {agent['stage']}")
        console.print(f"    Stalled for: {agent['minutes_stalled']} minutes")
        console.print()

    console.print("[dim]Use 'agenttree send <id> \"message\"' to nudge a stalled agent[/dim]")


@main.command()
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


@main.group()
def remote() -> None:
    """Manage remote agents via Tailscale + SSH."""
    pass


@remote.command("list")
def remote_list() -> None:
    """List available remote hosts on Tailscale network."""
    from agenttree.remote import is_tailscale_available, get_tailscale_hosts

    if not is_tailscale_available():
        console.print("[red]Error: Tailscale CLI not found[/red]")
        console.print("[dim]Install: https://tailscale.com/download[/dim]")
        sys.exit(1)

    hosts = get_tailscale_hosts()

    if not hosts:
        console.print("[yellow]No Tailscale hosts found[/yellow]")
        return

    table = Table(title="Tailscale Hosts")
    table.add_column("Hostname", style="cyan")

    for host in hosts:
        table.add_row(host)

    console.print(table)


@remote.command("start")
@click.argument("hostname")
@click.argument("agent_num", type=int)
@click.option("--user", default="agent", help="SSH user")
@click.option("--agents-repo", default="~/agents", help="Path to agents repo on remote")
def remote_start(hostname: str, agent_num: int, user: str, agents_repo: str) -> None:
    """Start a task on a remote agent.

    This will:
    1. SSH into the remote host
    2. Pull latest from _agenttree/ repo
    3. Notify the agent's tmux session

    Example:
        agenttree remote start my-home-pc 1
    """
    from agenttree.remote import RemoteHost, dispatch_task_to_remote_agent

    host = RemoteHost(name=hostname, host=hostname, user=user, is_tailscale=True)

    console.print(f"[cyan]Starting task on {hostname} agent-{agent_num}...[/cyan]")

    success = dispatch_task_to_remote_agent(
        host,
        agent_num,
        project_name="agenttree",  # Could be made configurable
        agents_repo_path=agents_repo
    )

    if success:
        console.print(f"[green]✓ Task started on {hostname}[/green]")
    else:
        console.print(f"[red]✗ Failed to start task[/red]")
        sys.exit(1)


# Add document creation commands
main.add_command(create_rfc)
main.add_command(create_investigation)
main.add_command(create_note)

# Add task management commands
main.add_command(complete)
main.add_command(resume)


# =============================================================================
# Issue Management Commands
# =============================================================================

@main.group()
def issue() -> None:
    """Manage agenttree issues.

    Issues are stored in _agenttree/issues/ and track work through
    the agenttree workflow stages.
    """
    pass


@issue.command("create")
@click.argument("title")
@click.option(
    "--priority", "-p",
    type=click.Choice(["low", "medium", "high", "critical"]),
    default="medium",
    help="Issue priority"
)
@click.option(
    "--label", "-l",
    multiple=True,
    help="Labels to add (can be used multiple times)"
)
@click.option(
    "--stage", "-s",
    type=click.Choice(["backlog", "define", "research", "implement"]),
    default="define",
    help="Starting stage for the issue (default: define)"
)
@click.option(
    "--flow", "-f",
    default="default",
    help="Workflow flow for this issue (default: 'default')"
)
@click.option(
    "--problem",
    required=True,
    help="Problem statement (fills problem.md) - required, min 50 chars"
)
@click.option(
    "--context",
    help="Context/background (fills problem.md)"
)
@click.option(
    "--solutions",
    help="Possible solutions (fills problem.md)"
)
@click.option(
    "--depends-on", "-d",
    multiple=True,
    help="Issue ID that must be completed first (can be used multiple times)"
)
@click.option(
    "--no-start",
    is_flag=True,
    help="Skip auto-starting an agent for this issue"
)
@click.pass_context
def issue_create(
    ctx: click.Context,
    title: str,
    priority: str,
    label: tuple,
    stage: str,
    flow: str,
    problem: str,
    context: Optional[str],
    solutions: Optional[str],
    depends_on: tuple,
    no_start: bool,
) -> None:
    """Create a new issue and auto-start an agent.

    Creates an issue directory in _agenttree/issues/ with:
    - issue.yaml (metadata)
    - problem.md (from --problem content)

    The --problem flag is required and must be at least 50 characters.
    Title must be at least 10 characters.

    After creation, an agent is automatically started for the issue. Use
    --no-start to skip auto-starting the agent.

    Issues with unmet dependencies are placed in backlog and auto-started when
    all dependencies are completed.

    Example:
        agenttree issue create "Fix login validation bug" --problem "Login fails silently when password contains special chars. Should show error message."
        agenttree issue create "Add dark mode toggle" -p high -l ui --problem "Users need dark mode. Add toggle in settings that persists preference."
        agenttree issue create "Feature B depends on A" --depends-on 053 --problem "This feature requires issue 053 to be completed first. It builds on that work."
        agenttree issue create "My feature title here" --problem "Description of the feature..." --no-start
    """
    # Validate title and problem length
    MIN_TITLE_LENGTH = 10
    MIN_PROBLEM_LENGTH = 50

    if len(title.strip()) < MIN_TITLE_LENGTH:
        console.print(f"[red]Error: Title must be at least {MIN_TITLE_LENGTH} characters (got {len(title.strip())})[/red]")
        sys.exit(1)

    if len(problem.strip()) < MIN_PROBLEM_LENGTH:
        console.print(f"[red]Error: Problem statement must be at least {MIN_PROBLEM_LENGTH} characters (got {len(problem.strip())})[/red]")
        console.print("[dim]Provide enough context for an agent to understand the issue.[/dim]")
        sys.exit(1)

    # Validate flow exists in config
    config = load_config()
    if flow not in config.flows:
        available_flows = list(config.flows.keys())
        console.print(f"[red]Error: Flow '{flow}' not found in configuration[/red]")
        if available_flows:
            console.print(f"[dim]Available flows: {', '.join(available_flows)}[/dim]")
        sys.exit(1)

    dependencies = list(depends_on) if depends_on else None

    # If dependencies are specified, check if they're all met
    # If not, force the issue to backlog stage
    effective_stage = stage
    has_unmet_deps = False

    if dependencies:
        # Create a temporary issue object just to check dependencies
        # We'll use the normalized deps for the check
        normalized_deps = []
        for dep in dependencies:
            dep_num = dep.lstrip("0") or "0"
            normalized_deps.append(f"{int(dep_num):03d}")

        # Check each dependency
        unmet = []
        for dep_id in normalized_deps:
            dep_issue = get_issue_func(dep_id)
            if dep_issue is None or dep_issue.stage != "accepted":
                unmet.append(dep_id)

        if unmet:
            has_unmet_deps = True
            effective_stage = "backlog"
            console.print(f"[yellow]Dependencies not met: {', '.join(unmet)}[/yellow]")
            console.print(f"[dim]Issue will be placed in backlog until dependencies complete[/dim]")

    try:
        issue = create_issue_func(
            title=title,
            priority=Priority(priority),
            labels=list(label) if label else None,
            stage=effective_stage,
            flow=flow,
            problem=problem,
            context=context,
            solutions=solutions,
            dependencies=dependencies,
        )
        console.print(f"[green]✓ Created issue {issue.id}: {issue.title}[/green]")
        console.print(f"[dim]  _agenttree/issues/{issue.id}-{issue.slug}/[/dim]")
        console.print(f"[dim]  Stage: {issue.stage} | Flow: {issue.flow}[/dim]")
        if issue.dependencies:
            console.print(f"[dim]  Dependencies: {', '.join(issue.dependencies)}[/dim]")

        # Auto-start agent unless blocked or --no-start specified
        if has_unmet_deps:
            console.print(f"\n[yellow]Issue blocked by dependencies - will auto-start when deps complete[/yellow]")
        elif no_start or effective_stage == "backlog":
            console.print(f"\n[bold]Next steps:[/bold]")
            console.print(f"  1. Fill in problem.md: [cyan]_agenttree/issues/{issue.id}-{issue.slug}/problem.md[/cyan]")
            console.print(f"  2. Start agent: [cyan]agenttree start {issue.id}[/cyan]")
        else:
            console.print(f"\n[cyan]Auto-starting agent...[/cyan]")
            ctx.invoke(start_agent, issue_id=issue.id)

    except Exception as e:
        console.print(f"[red]Error creating issue: {e}[/red]")
        sys.exit(1)


@issue.command("list")
@click.option(
    "--stage", "-s",
    help="Filter by stage (e.g., backlog, define, implement)"
)
@click.option(
    "--priority", "-p",
    type=click.Choice([p.value for p in Priority]),
    help="Filter by priority"
)
@click.option(
    "--json", "as_json",
    is_flag=True,
    help="Output as JSON"
)
def issue_list(stage: Optional[str], priority: Optional[str], as_json: bool) -> None:
    """List issues.

    Examples:
        agenttree issue list
        agenttree issue list --stage backlog
        agenttree issue list -s implement -p high
        agenttree issue list --json
    """
    stage_filter = stage if stage else None
    priority_filter = Priority(priority) if priority else None

    issues = list_issues_func(
        stage=stage_filter,
        priority=priority_filter,
    )

    if as_json:
        import json
        console.print(json.dumps([i.model_dump() for i in issues], indent=2))
        return

    if not issues:
        console.print("[yellow]No issues found[/yellow]")
        return

    table = Table(title="Issues")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Stage", style="magenta")
    table.add_column("Priority", style="yellow")

    for issue in issues:
        stage_str = issue.stage
        if issue.substage:
            stage_str += f".{issue.substage}"

        # Color priority
        priority_style = {
            Priority.CRITICAL: "red bold",
            Priority.HIGH: "yellow",
            Priority.MEDIUM: "white",
            Priority.LOW: "dim",
        }.get(issue.priority, "white")

        table.add_row(
            issue.id,
            issue.title[:40] + ("..." if len(issue.title) > 40 else ""),
            stage_str,
            f"[{priority_style}]{issue.priority.value}[/{priority_style}]",
        )

    console.print(table)


@issue.command("show")
@click.argument("issue_id")
@click.option("--json", "as_json", is_flag=True, help="Output full issue as JSON")
@click.option("--field", "field_name", help="Output just one field value (e.g., branch, worktree_dir, stage)")
def issue_show(issue_id: str, as_json: bool, field_name: Optional[str]) -> None:
    """Show issue details.

    Examples:
        agenttree issue show 001
        agenttree issue show 1
        agenttree issue show 001-fix-login

    Machine-readable output:
        agenttree issue show 060 --json
        agenttree issue show 060 --field branch
        agenttree issue show 060 --field worktree_dir
        agenttree issue show 060 --field stage
    """
    import json

    issue = get_issue_func(issue_id)

    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    # Machine-readable output modes
    if as_json or field_name:
        # Don't include docs by default for --field (faster), include for --json
        context = get_issue_context(issue, include_docs=as_json)

        if field_name:
            # Output single field value
            if field_name not in context:
                console.print(f"[red]Unknown field: {field_name}[/red]")
                console.print(f"[dim]Available fields: {', '.join(sorted(context.keys()))}[/dim]")
                sys.exit(1)
            value = context[field_name]
            # Print raw value for scripting (no formatting)
            if value is None:
                print("")
            elif isinstance(value, (list, dict)):
                print(json.dumps(value))
            else:
                print(value)
        else:
            # Output full JSON
            print(json.dumps(context, indent=2))
        return

    # Human-readable output (existing behavior)
    issue_dir = get_issue_dir(issue_id)

    console.print(f"\n[bold cyan]Issue {issue.id}: {issue.title}[/bold cyan]\n")

    # Basic info
    console.print(f"[bold]Stage:[/bold] {issue.stage}", end="")
    if issue.substage:
        console.print(f".{issue.substage}")
    else:
        console.print()

    console.print(f"[bold]Priority:[/bold] {issue.priority.value}")

    if issue.labels:
        console.print(f"[bold]Labels:[/bold] {', '.join(issue.labels)}")

    if issue.dependencies:
        from agenttree.issues import check_dependencies_met
        all_met, unmet = check_dependencies_met(issue)
        deps_str = ", ".join(issue.dependencies)
        if all_met:
            console.print(f"[bold]Dependencies:[/bold] {deps_str} [green](all met)[/green]")
        else:
            console.print(f"[bold]Dependencies:[/bold] {deps_str} [yellow](waiting on: {', '.join(unmet)})[/yellow]")

    if issue.branch:
        console.print(f"[bold]Branch:[/bold] {issue.branch}")

    if issue.pr_number:
        if issue.pr_url:
            console.print(f"[bold]PR:[/bold] #{issue.pr_number} - {issue.pr_url} (diff: {issue.pr_url}/files)")
        else:
            console.print(f"[bold]PR:[/bold] #{issue.pr_number}")

    if issue.github_issue:
        console.print(f"[bold]GitHub Issue:[/bold] #{issue.github_issue}")

    console.print(f"[bold]Created:[/bold] {issue.created}")
    console.print(f"[bold]Updated:[/bold] {issue.updated}")

    # Show files
    if issue_dir:
        console.print(f"\n[bold]Files:[/bold]")
        for file in sorted(issue_dir.iterdir()):
            if file.is_file():
                console.print(f"  • {file.name}")

    # Show history
    if issue.history:
        console.print(f"\n[bold]History:[/bold]")
        for entry in issue.history[-5:]:  # Last 5 entries
            stage_str = entry.stage
            if entry.substage:
                stage_str += f".{entry.substage}"
            agent_str = f" (agent {entry.agent})" if entry.agent else ""
            console.print(f"  • {entry.timestamp[:10]} → {stage_str}{agent_str}")

    console.print(f"\n[dim]Directory: {issue_dir}[/dim]")


@issue.command("set-priority")
@click.argument("issue_id")
@click.argument("priority", type=click.Choice([p.value for p in Priority]))
def issue_set_priority(issue_id: str, priority: str) -> None:
    """Set the priority of an issue.

    Examples:
        agenttree issue set-priority 001 high
        agenttree issue set-priority 42 critical
    """
    from agenttree.issues import update_issue_priority

    issue = get_issue_func(issue_id)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    updated = update_issue_priority(issue.id, Priority(priority))
    if not updated:
        console.print(f"[red]Failed to update priority[/red]")
        sys.exit(1)

    priority_style = {
        "critical": "red",
        "high": "yellow",
        "medium": "cyan",
        "low": "green",
    }.get(priority, "white")

    console.print(f"[green]✓[/green] Priority set to [{priority_style}]{priority}[/{priority_style}] for issue #{issue.id}")


@issue.command("doc")
@click.argument("doc_type", type=click.Choice(["problem", "plan", "review", "research"]))
@click.option("--issue", "-i", "issue_id", required=True, help="Issue ID")
def issue_doc(doc_type: str, issue_id: str) -> None:
    """Create or show path to an issue documentation file.

    Creates the file from template if it doesn't exist, then prints the path.
    Use this to ensure documentation goes in the right place.

    Examples:
        agenttree issue doc problem --issue 026
        agenttree issue doc research --issue 026
        agenttree issue doc plan --issue 026
        agenttree issue doc review --issue 026
    """
    issue = get_issue_func(issue_id)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    issue_dir = get_issue_dir(issue_id)
    if not issue_dir:
        console.print(f"[red]Issue directory not found[/red]")
        sys.exit(1)

    doc_file = issue_dir / f"{doc_type}.md"

    # Create from template if doesn't exist
    if not doc_file.exists():
        templates_dir = Path.cwd() / "_agenttree" / "templates"
        template_file = templates_dir / f"{doc_type}.md"

        if template_file.exists():
            content = template_file.read_text()
            # Replace template variables
            content = content.replace("{{issue_id}}", issue.id)
            content = content.replace("{{title}}", issue.title)
            doc_file.write_text(content)
            console.print(f"[green]✓ Created {doc_type}.md from template[/green]")
        else:
            # Create with basic header
            doc_file.write_text(f"# {doc_type.title()} - Issue #{issue.id}\n\n")
            console.print(f"[green]✓ Created {doc_type}.md[/green]")

    console.print(f"\n[bold]Path:[/bold] {doc_file}")
    console.print(f"\n[dim]Write your {doc_type} documentation to this file.[/dim]")


@issue.command("check-deps")
def issue_check_deps() -> None:
    """Check all blocked issues and their dependency status.

    Shows issues in backlog that have dependencies and whether
    those dependencies are met or still pending.

    Example:
        agenttree issue check-deps
    """
    from agenttree.issues import check_dependencies_met, get_ready_issues

    blocked_issues = list_issues_func(stage="backlog")

    if not blocked_issues:
        console.print("[dim]No issues in backlog[/dim]")
        return

    # Filter to only issues with dependencies
    issues_with_deps = [i for i in blocked_issues if i.dependencies]

    if not issues_with_deps:
        console.print("[dim]No issues in backlog with dependencies[/dim]")
        return

    table = Table(title="Blocked Issues in Backlog")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Dependencies", style="yellow")
    table.add_column("Status", style="magenta")

    for issue in issues_with_deps:
        all_met, unmet = check_dependencies_met(issue)
        deps_str = ", ".join(issue.dependencies)

        if all_met:
            status = "[green]✓ Ready to start[/green]"
        else:
            status = f"[red]Blocked by: {', '.join(unmet)}[/red]"

        table.add_row(
            issue.id,
            issue.title[:35] + ("..." if len(issue.title) > 35 else ""),
            deps_str,
            status,
        )

    console.print(table)

    # Show ready issues
    ready = get_ready_issues()
    if ready:
        console.print(f"\n[green]Ready to start: {', '.join(i.id for i in ready)}[/green]")
        console.print("[dim]These will auto-start when their dependencies are accepted[/dim]")


# =============================================================================
# Stage Transition Commands
# =============================================================================

@main.command("status")
@click.option("--issue", "-i", "issue_id", help="Issue ID (if not in agent context)")
def stage_status(issue_id: Optional[str]) -> None:
    """Show current issue and stage status.

    Examples:
        agenttree status
        agenttree status --issue 001
    """
    # Try to get issue from argument or agent context
    if not issue_id:
        # TODO: Read from .agenttree-agent file when in agent worktree
        console.print("[dim]Showing all active issues (use --issue ID for details):[/dim]\n")

        # Show all non-backlog, non-accepted issues
        active_issues = [
            i for i in list_issues_func()
            if i.stage not in (BACKLOG, ACCEPTED, NOT_DOING)
        ]

        if not active_issues:
            console.print("[dim]No active issues[/dim]")
            return

        from datetime import datetime, timezone
        from agenttree.config import load_config
        
        config = load_config()
        stage_names = [s.name for s in config.stages]
        total_stages = len(stage_names)

        table = Table(title="Active Issues")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Stage", style="magenta")
        table.add_column("Time", style="yellow", justify="right")

        for active_issue in active_issues:
            # Get stage index (1-based)
            try:
                stage_idx = stage_names.index(active_issue.stage) + 1
                stage_num = f"{stage_idx}/{total_stages} "
            except ValueError:
                stage_num = ""
            
            stage_str = stage_num + active_issue.stage
            if active_issue.substage:
                stage_str += f".{active_issue.substage}"
            
            # Calculate time in current stage
            time_str = ""
            try:
                updated = datetime.fromisoformat(active_issue.updated.replace("Z", "+00:00"))
                elapsed = datetime.now(timezone.utc) - updated
                mins = int(elapsed.total_seconds() / 60)
                if mins < 60:
                    time_str = f"{mins}m"
                elif mins < 1440:  # Less than 24 hours
                    time_str = f"{mins // 60}h {mins % 60}m"
                else:
                    days = mins // 1440
                    time_str = f"{days}d {(mins % 1440) // 60}h"
            except (ValueError, TypeError):
                time_str = "?"
            
            table.add_row(active_issue.id, active_issue.title[:40], stage_str, time_str)

        console.print(table)
        return

    issue = get_issue_func(issue_id)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]Issue {issue.id}: {issue.title}[/bold cyan]")
    console.print(f"[bold]Stage:[/bold] {issue.stage}", end="")
    if issue.substage:
        console.print(f".{issue.substage}")
    else:
        console.print()

    # Check if waiting for non-agent host
    from agenttree.config import load_config
    config_for_status = load_config()
    status_stage_config = config_for_status.get_stage(issue.stage)
    if status_stage_config and status_stage_config.role != "developer":
        if status_stage_config.role == "manager":
            console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
        else:
            console.print(f"\n[yellow]⏳ Waiting for '{status_stage_config.role}' agent[/yellow]")
    elif issue.stage == ACCEPTED:
        console.print(f"\n[green]✓ Issue completed[/green]")


@main.command("next")
@click.option("--issue", "-i", "issue_id", required=False, help="Issue ID (auto-detected from branch if not provided)")
@click.option("--reassess", is_flag=True, help="Go back to plan_assess for another review cycle")
def stage_next(issue_id: Optional[str], reassess: bool) -> None:
    """Move to the next substage or stage.

    Examples:
        agenttree next --issue 001
        agenttree next  # Auto-detects issue from branch
        agenttree next --reassess  # Cycle back to plan_assess from plan_revise
    """
    from agenttree.issues import get_issue_from_branch

    # Auto-detect issue from branch if not provided
    if not issue_id:
        issue_id = get_issue_from_branch()
        if not issue_id:
            console.print("[red]No issue ID provided and couldn't detect from branch name[/red]")
            console.print("[dim]Use --issue <ID> or run from a branch like 'issue-042-slug'[/dim]")
            sys.exit(1)
        console.print(f"[dim]Detected issue {issue_id} from branch[/dim]")

    issue = get_issue_func(issue_id)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    if issue.stage == ACCEPTED:
        console.print(f"[yellow]Issue is already accepted[/yellow]")
        return

    if issue.stage == NOT_DOING:
        console.print(f"[yellow]Issue is marked as not doing[/yellow]")
        return

    # Block agents from operating in manager (human review) stages only
    # Other agent stages can be advanced - hooks will enforce requirements
    from agenttree.config import load_config
    config = load_config()
    stage_config = config.get_stage(issue.stage)
    if stage_config:
        stage_role = stage_config.role
        current_role = get_current_role()
        # Only block if this is a manager stage and we're not the manager
        if stage_role == "manager" and current_role != "manager":
            console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
            console.print(f"[dim]Stage '{issue.stage}' requires human review.[/dim]")
            console.print(f"[dim]A human will run 'agenttree approve {issue.id}' when ready.[/dim]")
            return

    # Check for restart and re-orient if needed
    session = get_session(issue_id)
    if session is None:
        # No session exists - create one (fresh start or legacy case)
        session = create_session(issue_id)

    if is_restart(issue_id, issue.stage, issue.substage):
        # This is a restart - re-orient the agent instead of advancing
        console.print(f"\n[cyan]🔄 Session restart detected[/cyan]")
        console.print(f"[dim]Resuming work on issue #{issue.id}: {issue.title}[/dim]\n")

        stage_str = issue.stage
        if issue.substage:
            stage_str += f".{issue.substage}"
        console.print(f"[bold]Current stage:[/bold] {stage_str}")

        # Show existing files
        issue_dir = get_issue_dir(issue_id)
        if issue_dir:
            existing_files = [f.name for f in issue_dir.iterdir() if f.is_file() and not f.name.startswith('.')]
            if existing_files:
                console.print(f"[bold]Existing work:[/bold] {', '.join(existing_files)}")

        # Show uncommitted changes if any (both staged and unstaged)
        import subprocess
        try:
            result = subprocess.run(
                ["git", "diff", "--stat", "HEAD"],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                console.print(f"\n[bold]Uncommitted changes:[/bold]")
                console.print(result.stdout[:500])
        except Exception:
            pass

        # Determine if this is a takeover (not starting from beginning)
        is_takeover = issue.stage not in (BACKLOG, DEFINE)

        # Load and display persona for context
        persona = load_persona(
            agent_type="developer",  # TODO: Get from host config
            issue=issue,
            is_takeover=is_takeover,
            current_stage=issue.stage,
            current_substage=issue.substage,
        )
        if persona:
            console.print(f"\n{'='*60}")
            console.print(f"[bold cyan]AGENT PERSONA[/bold cyan]")
            console.print(f"{'='*60}\n")
            console.print(persona)

            # Add takeover context message
            if is_takeover:
                console.print(f"\n[yellow]{'='*60}[/yellow]")
                console.print(f"[bold yellow]TAKEOVER NOTICE[/bold yellow]")
                console.print(f"[yellow]{'='*60}[/yellow]\n")
                console.print(
                    f"You are taking over for another agent who completed stages before [bold]{issue.stage}[/bold].\n"
                    f"Please review their work in the existing files and continue from here."
                )

        # Load and display current stage instructions
        skill = load_skill(issue.stage, issue.substage, issue=issue)
        if skill:
            console.print(f"\n{'='*60}")
            console.print(f"[bold cyan]Continue working on: {issue.stage.upper()}[/bold cyan]")
            console.print(f"{'='*60}\n")
            console.print(skill)

        console.print(f"\n[dim]When ready to advance, run 'agenttree next' again.[/dim]")

        # Mark as oriented and sync stage so next call will advance
        mark_session_oriented(issue_id, issue.stage, issue.substage)
        return

    # Handle --reassess flag for plan revision cycling
    if reassess:
        if issue.stage != PLAN_REVISE:
            console.print(f"[red]--reassess only works from plan_revise stage[/red]")
            sys.exit(1)
        next_stage = PLAN_ASSESS
        next_substage = None
        is_human_review = False
    else:
        # Calculate next stage
        next_stage, next_substage, is_human_review = get_next_stage(
            issue.stage, issue.substage, issue.flow
        )

    # Check if we're already at the next stage (no change)
    if next_stage == issue.stage and next_substage == issue.substage:
        console.print(f"[yellow]Already at final stage[/yellow]")
        return

    # Execute exit hooks (can block with ValidationError or redirect with StageRedirect)
    from_stage = issue.stage
    from_substage = issue.substage
    try:
        execute_exit_hooks(issue, from_stage, from_substage)
    except StageRedirect as redirect:
        # Redirect to a different stage instead of normal next stage
        console.print(f"[yellow]Redirecting to {redirect.target_stage}: {redirect.reason}[/yellow]")
        next_stage = redirect.target_stage
        next_substage = None
        is_human_review = False  # Redirect target is typically not human review
    except ValidationError as e:
        console.print(f"[red]Cannot proceed: {e}[/red]")
        sys.exit(1)

    # Save tmux history if enabled in config
    config = load_config()
    if config.save_tmux_history:
        issue_dir = get_issue_dir(issue_id)
        if issue_dir:
            session_name = config.get_issue_tmux_session(issue_id)
            stage_str = from_stage
            if from_substage:
                stage_str += f".{from_substage}"
            history_file = issue_dir / "tmux_history.log"
            if save_tmux_history_to_file(session_name, history_file, stage_str):
                console.print(f"[dim]Saved tmux history to {history_file.name}[/dim]")

    # Update issue stage in database
    updated = update_issue_stage(issue_id, next_stage, next_substage)
    if not updated:
        console.print(f"[red]Failed to update issue[/red]")
        sys.exit(1)

    # Update session to track stage advancement
    update_session_stage(issue_id, next_stage, next_substage)

    # Execute enter hooks (after stage updated)
    execute_enter_hooks(updated, next_stage, next_substage)

    stage_str = next_stage
    if next_substage:
        stage_str += f".{next_substage}"
    console.print(f"[green]✓ Moved to {stage_str}[/green]")

    # Check if next stage requires a different host
    next_stage_config = config.get_stage(next_stage)
    if next_stage_config and next_stage_config.role != "developer" and is_running_in_container():
        if next_stage_config.role == "manager" or is_human_review:
            console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
            console.print(f"[dim]Your work has been submitted for review.[/dim]")
            console.print(f"[dim]You will receive instructions when the review is complete.[/dim]")
        else:
            console.print(f"\n[yellow]⏳ Waiting for '{next_stage_config.role}' agent[/yellow]")
            console.print(f"[dim]The '{next_stage_config.role}' agent will handle the next stage.[/dim]")
            console.print(f"[dim]You will receive instructions when that stage is complete.[/dim]")
        return

    # Determine if this is first agent entry (should include AGENTS.md system prompt)
    is_first_stage = next_stage == DEFINE and from_stage == BACKLOG

    # Load and display skill for next stage with Jinja rendering
    skill = load_skill(next_stage, next_substage, issue=updated, include_system=is_first_stage)
    if skill:
        console.print(f"\n{'='*60}")
        header = f"Stage Instructions: {next_stage.upper()}"
        if next_substage:
            header += f" ({next_substage})"
        console.print(f"[bold cyan]{header}[/bold cyan]")
        console.print(f"{'='*60}\n")
        console.print(skill)


@main.command("approve")
@click.argument("issue_id", type=str)
@click.option("--skip-approval", is_flag=True, help="Skip PR approval check (useful if you're the PR author)")
def approve_issue(issue_id: str, skip_approval: bool) -> None:
    """Approve an issue at a human review stage.

    Only works at human review stages (plan_review, implementation_review).
    Cannot be run from inside a container - humans only.

    For implementation_review: will auto-approve the PR on GitHub unless you're the author.
    Use --skip-approval to bypass if you've already reviewed the changes.

    Example:
        agenttree approve 042
        agenttree approve 042 --skip-approval  # Skip PR approval check
    """
    # Block if in container
    if is_running_in_container():
        console.print(f"[red]Error: 'approve' cannot be run from inside a container[/red]")
        console.print(f"[dim]This command is for human reviewers only.[/dim]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    # Check if at a stage that requires human approval (human_review=true or role=manager)
    from agenttree.config import load_config
    approve_config = load_config()
    approve_stage_config = approve_config.get_stage(issue.stage)
    if not approve_stage_config or not (approve_stage_config.human_review or approve_stage_config.role == "manager"):
        human_review_stages = approve_config.get_human_review_stages()
        console.print(f"[red]Issue is at '{issue.stage}', not a human review stage[/red]")
        console.print(f"[dim]Human review stages: {', '.join(human_review_stages)}[/dim]")
        sys.exit(1)

    # Calculate next stage
    next_stage, next_substage, _ = get_next_stage(issue.stage, issue.substage, issue.flow)

    # Execute exit hooks
    from_stage = issue.stage
    from_substage = issue.substage
    try:
        execute_exit_hooks(issue, from_stage, from_substage, skip_pr_approval=skip_approval)
    except StageRedirect as redirect:
        # Redirect to a different stage instead of normal next stage
        console.print(f"[yellow]Redirecting to {redirect.target_stage}: {redirect.reason}[/yellow]")
        next_stage = redirect.target_stage
        next_substage = None
    except ValidationError as e:
        console.print(f"[red]Cannot approve: {e}[/red]")
        sys.exit(1)

    # Update issue stage
    updated = update_issue_stage(issue_id_normalized, next_stage, next_substage)
    if not updated:
        console.print(f"[red]Failed to update issue[/red]")
        sys.exit(1)

    # Update session (last_stage will differ from issue.stage, triggering re-orient)
    # Note: We intentionally DON'T call update_session_stage here because that would
    # sync last_stage, defeating the stage mismatch detection in is_restart()

    # Execute enter hooks (after stage updated)
    execute_enter_hooks(updated, next_stage, next_substage)

    stage_str = next_stage
    if next_substage:
        stage_str += f".{next_substage}"
    console.print(f"[green]✓ Approved! Issue #{issue.id} moved to {stage_str}[/green]")

    # Auto-notify agent to continue (if active)
    from agenttree.state import get_active_agent

    agent = get_active_agent(issue_id_normalized)
    if agent:
        config = load_config()
        tmux_manager = TmuxManager(config)
        if tmux_manager.is_issue_running(agent.tmux_session):
            message = "Your work was approved! Run `agenttree next` for instructions."
            tmux_manager.send_message_to_issue(agent.tmux_session, message)
            console.print(f"[green]✓ Notified agent to continue[/green]")


@main.command("defer")
@click.argument("issue_id", type=str)
def defer_issue(issue_id: str) -> None:
    """Move an issue to backlog (defer for later).

    This removes the issue from active work. Any running agent should be stopped.

    Example:
        agenttree defer 042
    """
    # Block if in container
    if is_running_in_container():
        console.print(f"[red]Error: 'defer' cannot be run from inside a container[/red]")
        console.print(f"[dim]This command is for human reviewers only.[/dim]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    if issue.stage == BACKLOG:
        console.print(f"[yellow]Issue is already in backlog[/yellow]")
        return

    if issue.stage == ACCEPTED:
        console.print(f"[yellow]Issue is already accepted, cannot defer[/yellow]")
        return

    # Move to backlog
    updated = update_issue_stage(issue_id_normalized, BACKLOG, None)
    if not updated:
        console.print(f"[red]Failed to update issue[/red]")
        sys.exit(1)

    # Delete session (agent should be stopped)
    delete_session(issue_id_normalized)

    console.print(f"[green]✓ Issue #{issue.id} moved to backlog[/green]")
    console.print(f"\n[dim]Stop the agent if running:[/dim]")
    console.print(f"  agenttree kill {issue.id}")


@main.command("shutdown")
@click.argument("issue_id")
@click.argument("stage", type=click.Choice(["backlog", "not_doing", "accepted"]))
@click.option(
    "--changes", "-c",
    type=click.Choice(["stash", "commit", "discard", "error"]),
    default=None,
    help="How to handle uncommitted changes (default: stage-specific)"
)
@click.option(
    "--keep-worktree/--remove-worktree",
    default=None,
    help="Override worktree handling (default: keep for backlog, remove for others)"
)
@click.option(
    "--keep-branch/--delete-branch",
    default=None,
    help="Override branch handling (default: keep for backlog/accepted, delete for not_doing)"
)
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Skip confirmation prompts"
)
@click.option(
    "--message", "-m",
    default="WIP: shutdown",
    help="Commit message when using --changes commit"
)
def shutdown_issue(
    issue_id: str,
    stage: str,
    changes: Optional[str],
    keep_worktree: Optional[bool],
    keep_branch: Optional[bool],
    force: bool,
    message: str,
) -> None:
    """Shutdown an issue's agent and clean up resources.

    Stops the agent, handles uncommitted changes, and optionally removes
    the worktree and branch. The STAGE determines the default behavior:

    \b
    backlog:   Pause work. Keep worktree/branch, stash changes.
    not_doing: Abandon work. Remove worktree, delete branch, discard changes.
    accepted:  Work complete. Remove worktree, keep branch, error on uncommitted.

    Examples:
        agenttree shutdown 042 backlog           # Pause for later
        agenttree shutdown 042 not_doing         # Abandon issue
        agenttree shutdown 042 not_doing -f      # Abandon without prompts
        agenttree shutdown 042 backlog -c commit # Commit changes instead of stash
    """
    from agenttree.state import get_active_agent, unregister_agent
    from agenttree.worktree import remove_worktree

    # Block if in container
    if is_running_in_container():
        console.print("[red]Error: 'shutdown' cannot be run from inside a container[/red]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    # Check if already in target stage - return early
    if issue.stage == stage:
        console.print(f"[yellow]Issue #{issue.id} is already in {stage}[/yellow]")
        return

    # Set defaults based on stage
    if changes is None:
        if stage == "backlog":
            changes = "stash"
        elif stage == "not_doing":
            changes = "discard"
        else:  # accepted
            changes = "error"

    if keep_worktree is None:
        keep_worktree = stage == "backlog"

    if keep_branch is None:
        keep_branch = stage != "not_doing"

    config = load_config()
    repo_path = Path.cwd()

    # Stop ALL agents for this issue FIRST to avoid race conditions with worktree operations
    from agenttree.state import stop_all_agents_for_issue
    count = stop_all_agents_for_issue(issue_id_normalized, quiet=True)
    if count > 0:
        console.print(f"[dim]Stopped {count} agent(s) for issue #{issue.id}[/dim]")

    # Get worktree path
    worktree_path = None
    if issue.worktree_dir:
        worktree_path = repo_path / issue.worktree_dir
        if not worktree_path.exists():
            worktree_path = None

    # Handle uncommitted changes in worktree
    if worktree_path and worktree_path.exists():
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )
        has_changes = bool(status_result.stdout.strip())

        if has_changes:
            if changes == "error":
                console.print("[red]Error: Uncommitted changes in worktree[/red]")
                console.print("[dim]Use --changes stash|commit|discard to handle them[/dim]")
                sys.exit(1)
            elif changes == "discard":
                if not force:
                    console.print("[yellow]Warning: Uncommitted changes will be discarded:[/yellow]")
                    console.print(status_result.stdout)
                    if not click.confirm("Discard changes?"):
                        console.print("[dim]Aborted[/dim]")
                        sys.exit(0)
                try:
                    subprocess.run(["git", "checkout", "."], cwd=worktree_path, check=True, capture_output=True)
                    subprocess.run(["git", "clean", "-fd"], cwd=worktree_path, check=True, capture_output=True)
                    console.print("[dim]Discarded uncommitted changes[/dim]")
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]Error discarding changes: {e}[/red]")
                    sys.exit(1)
            elif changes == "stash":
                try:
                    subprocess.run(["git", "stash", "push", "-m", f"shutdown: {issue.id}"], cwd=worktree_path, check=True, capture_output=True)
                    console.print("[dim]Stashed uncommitted changes[/dim]")
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]Error stashing changes: {e}[/red]")
                    sys.exit(1)
            elif changes == "commit":
                try:
                    subprocess.run(["git", "add", "-A"], cwd=worktree_path, check=True, capture_output=True)
                    subprocess.run(["git", "commit", "-m", message], cwd=worktree_path, check=True, capture_output=True)
                    console.print(f"[dim]Committed changes: {message}[/dim]")
                except subprocess.CalledProcessError as e:
                    console.print(f"[red]Error committing changes: {e}[/red]")
                    sys.exit(1)

        # Check for unpushed commits - handle case where branch has no upstream
        has_unpushed = False
        unpushed_output = ""

        # First try checking against upstream
        unpushed_result = subprocess.run(
            ["git", "log", "--oneline", "@{u}..HEAD"],
            cwd=worktree_path,
            capture_output=True,
            text=True,
        )

        if unpushed_result.returncode == 0:
            # Upstream exists, check if there are unpushed commits
            has_unpushed = bool(unpushed_result.stdout.strip())
            unpushed_output = unpushed_result.stdout
        else:
            # No upstream - check against origin/main as fallback
            # This catches local-only branches that were never pushed
            fallback_result = subprocess.run(
                ["git", "log", "--oneline", "origin/main..HEAD"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            )
            if fallback_result.returncode == 0 and fallback_result.stdout.strip():
                has_unpushed = True
                unpushed_output = fallback_result.stdout
                console.print("[yellow]Warning: Branch has no upstream tracking branch[/yellow]")

        if has_unpushed and not keep_branch:
            if not force:
                console.print("[yellow]Warning: Unpushed commits will be lost:[/yellow]")
                console.print(unpushed_output)
                if not click.confirm("Continue anyway?"):
                    console.print("[dim]Aborted[/dim]")
                    sys.exit(0)

    # Remove worktree if requested
    if not keep_worktree and worktree_path and worktree_path.exists():
        remove_worktree(repo_path, worktree_path)
        console.print(f"[dim]Removed worktree: {worktree_path}[/dim]")
        # Clear worktree_dir in issue metadata
        update_issue_metadata(issue_id_normalized, worktree_dir="")

    # Delete branch if requested
    if not keep_branch and issue.branch:
        # Delete local branch (may fail if checked out elsewhere, that's ok)
        subprocess.run(
            ["git", "branch", "-D", issue.branch],
            cwd=repo_path,
            capture_output=True,
        )
        console.print(f"[dim]Deleted local branch: {issue.branch}[/dim]")

    # Update issue stage
    if issue.stage != stage:
        updated = update_issue_stage(issue_id_normalized, stage, None)
        if not updated:
            console.print(f"[red]Failed to update issue stage[/red]")
            sys.exit(1)

    # Delete session file
    delete_session(issue_id_normalized)

    console.print(f"[green]✓ Issue #{issue.id} shutdown to {stage}[/green]")


# =============================================================================
# Agent Context Commands
# =============================================================================

@main.command("context-init")
@click.option("--agent", "-a", "agent_num", type=int, help="Agent number (reads from .env if not provided)")
@click.option("--port", "-p", "port", type=int, help="Agent port (derived from agent number if not provided)")
def context_init(agent_num: Optional[int], port: Optional[int]) -> None:
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


@main.command()
@click.argument("extra_args", nargs=-1)
def test(extra_args: tuple[str, ...]) -> None:
    """Run the project's test commands.

    Uses commands.test from .agenttree.yaml config.
    Runs all commands and reports all errors (doesn't stop on first failure).
    """
    config = load_config()
    test_cmd = config.commands.get("test")

    if not test_cmd:
        console.print("[red]Error: test command not configured[/red]")
        console.print("\nAdd to .agenttree.yaml:")
        console.print("  commands:")
        console.print("    test: pytest")
        sys.exit(1)

    # Normalize to list
    commands = test_cmd if isinstance(test_cmd, list) else [test_cmd]

    failed = []
    for cmd in commands:
        # Append extra arguments to each command
        if extra_args:
            cmd = f"{cmd} {' '.join(extra_args)}"

        console.print(f"[dim]Running: {cmd}[/dim]")
        result = subprocess.run(cmd, shell=True)

        if result.returncode != 0:
            failed.append(cmd)

    if failed:
        console.print(f"\n[red]Failed commands ({len(failed)}/{len(commands)}):[/red]")
        for cmd in failed:
            console.print(f"  - {cmd}")
        sys.exit(1)

    console.print(f"\n[green]All {len(commands)} test command(s) passed[/green]")


@main.command()
@click.argument("extra_args", nargs=-1)
def lint(extra_args: tuple[str, ...]) -> None:
    """Run the project's lint commands.

    Uses commands.lint from .agenttree.yaml config.
    Runs all commands and reports all errors (doesn't stop on first failure).
    """
    config = load_config()
    lint_cmd = config.commands.get("lint")

    if not lint_cmd:
        console.print("[red]Error: lint command not configured[/red]")
        console.print("\nAdd to .agenttree.yaml:")
        console.print("  commands:")
        console.print("    lint: ruff check .")
        sys.exit(1)

    # Normalize to list
    commands = lint_cmd if isinstance(lint_cmd, list) else [lint_cmd]

    failed = []
    for cmd in commands:
        # Append extra arguments to each command
        if extra_args:
            cmd = f"{cmd} {' '.join(extra_args)}"

        console.print(f"[dim]Running: {cmd}[/dim]")
        result = subprocess.run(cmd, shell=True)

        if result.returncode != 0:
            failed.append(cmd)

    if failed:
        console.print(f"\n[red]Failed commands ({len(failed)}/{len(commands)}):[/red]")
        for cmd in failed:
            console.print(f"  - {cmd}")
        sys.exit(1)

    console.print(f"\n[green]All {len(commands)} lint command(s) passed[/green]")


# =============================================================================
# Sync Command
# =============================================================================


@main.command("sync")
def sync_command() -> None:
    """Force sync with agents repository.

    This command:
    1. Pushes any pending branches to remote
    2. Creates PRs for issues at implementation_review that don't have PRs
    3. Detects PRs that were merged externally and advances issues to accepted

    Sync happens automatically on most agenttree commands, but use this
    to force it immediately (e.g., right after an agent finishes).

    Example:
        agenttree sync
    """
    from agenttree.agents_repo import sync_agents_repo
    from agenttree.controller_hooks import run_post_controller_hooks
    from agenttree.issues import get_agenttree_path

    console.print("[dim]Syncing agents repository...[/dim]")
    agents_path = get_agenttree_path()
    success = sync_agents_repo(agents_path)

    if success:
        console.print("[green]✓ Sync complete[/green]")
    else:
        console.print("[yellow]Sync completed with warnings[/yellow]")

    # Run controller hooks (stall detection, CI checks, etc.)
    console.print("[dim]Running controller hooks...[/dim]")
    run_post_controller_hooks(agents_path)


# =============================================================================
# Hooks Commands
# =============================================================================


@main.group("hooks")
def hooks_group() -> None:
    """Hook management commands."""
    pass


@hooks_group.command("check")
@click.argument("issue_id", type=str)
@click.option("--event", type=click.Choice(["pre_completion", "post_start", "both"]), default="both",
              help="Which hooks to show (default: both)")
def hooks_check(issue_id: str, event: str) -> None:
    """Preview which hooks would run for an issue.

    Shows the hooks that would execute for the issue's current stage,
    without actually running them. Useful for debugging workflow issues.

    Example:
        agenttree hooks check 042
        agenttree hooks check 042 --event pre_completion
    """
    from agenttree.config import load_config
    from agenttree.hooks import parse_hook, is_running_in_container

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    config = load_config()
    stage_config = config.get_stage(issue.stage)
    if not stage_config:
        console.print(f"[yellow]No hooks configured for stage: {issue.stage}[/yellow]")
        return

    in_container = is_running_in_container()
    context = "container" if in_container else "host"

    console.print(f"\n[bold]Issue #{issue.id}[/bold]: {issue.title}")
    console.print(f"[dim]Stage: {issue.stage}" + (f".{issue.substage}" if issue.substage else "") + f"[/dim]")
    console.print(f"[dim]Context: {context}[/dim]")
    console.print()

    def show_hooks(hooks: list, event_name: str, source: str) -> None:
        if not hooks:
            console.print(f"[dim]{event_name} ({source}): none[/dim]")
            return

        console.print(f"[cyan]{event_name} ({source}):[/cyan]")
        for hook in hooks:
            hook_type, params = parse_hook(hook)
            host_only = hook.get("host_only", False)
            optional = hook.get("optional", False)

            # Check if would be skipped
            skipped = ""
            if host_only and in_container:
                skipped = " [yellow](would skip - host only)[/yellow]"
            elif hook_type in ("merge_pr", "pr_approved", "cleanup_agent", "start_blocked_issues") and in_container:
                skipped = " [yellow](would skip - needs host)[/yellow]"

            optional_str = " [dim](optional)[/dim]" if optional else ""

            # Format params
            if hook_type == "run":
                param_str = params.get("command", "")
            elif hook_type == "file_exists":
                param_str = params.get("file", "")
            elif hook_type == "section_check":
                param_str = f"{params.get('file', '')} → {params.get('section', '')} ({params.get('expect', '')})"
            elif hook_type == "field_check":
                param_str = f"{params.get('file', '')} → {params.get('path', '')} (min: {params.get('min', 'n/a')})"
            elif hook_type == "create_file":
                param_str = f"{params.get('template', '')} → {params.get('dest', '')}"
            else:
                param_str = str(params) if params else ""

            console.print(f"  • [green]{hook_type}[/green]: {param_str}{optional_str}{skipped}")

    # Get substage config if applicable
    substage_config = None
    if issue.substage:
        substage_config = stage_config.get_substage(issue.substage)

    # Show hooks based on event filter
    if event in ("pre_completion", "both"):
        # Substage pre_completion hooks
        if substage_config:
            show_hooks(substage_config.pre_completion, "pre_completion", f"{issue.stage}.{issue.substage}")

        # Check if exiting stage (last substage or no substages)
        substages = stage_config.substage_order()
        is_exiting_stage = not substages or (issue.substage and substages[-1] == issue.substage)

        if is_exiting_stage:
            show_hooks(stage_config.pre_completion, "pre_completion", f"{issue.stage} (stage-level)")
        elif not substage_config:
            show_hooks(stage_config.pre_completion, "pre_completion", issue.stage)

    if event in ("post_start", "both"):
        # For post_start, show what would run on NEXT stage
        next_stage, next_substage, _ = get_next_stage(issue.stage, issue.substage, issue.flow)
        if next_stage:
            next_stage_config = config.get_stage(next_stage)
            if next_stage_config:
                if next_substage:
                    next_substage_config = next_stage_config.get_substage(next_substage)
                    if next_substage_config:
                        show_hooks(next_substage_config.post_start, "post_start", f"{next_stage}.{next_substage} (next)")
                else:
                    show_hooks(next_stage_config.post_start, "post_start", f"{next_stage} (next)")

    console.print()


def _execute_rollback(
    issue_id: str,
    target_stage: str,
    yes: bool = True,
    reset_worktree: bool = False,
    keep_changes: bool = True,
    skip_sync: bool = False,
) -> bool:
    """Execute a rollback programmatically. Used by both CLI and hooks.

    This is a thin wrapper around agenttree.rollback.execute_rollback to avoid
    circular imports between hooks.py and cli.py.

    Args:
        issue_id: Issue ID to rollback
        target_stage: Stage to rollback to
        yes: Auto-confirm (default True for programmatic use)
        reset_worktree: Reset worktree to origin/main
        keep_changes: Keep code changes (default True)
        skip_sync: Skip syncing changes (for hook use where caller handles sync)

    Returns:
        True if rollback succeeded, False otherwise
    """
    from agenttree.rollback import execute_rollback
    return execute_rollback(
        issue_id=issue_id,
        target_stage=target_stage,
        yes=yes,
        reset_worktree=reset_worktree,
        keep_changes=keep_changes,
        skip_sync=skip_sync,
    )


@main.command("rollback")
@click.argument("issue_id", type=str)
@click.argument("stage_name", type=str)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.option(
    "--reset-worktree",
    is_flag=True,
    help="Reset worktree to origin/main (discards code changes)",
)
@click.option(
    "--keep-changes",
    is_flag=True,
    help="Keep code changes in worktree (default for pre-implement stages)",
)
def rollback_issue(
    issue_id: str,
    stage_name: str,
    yes: bool,
    reset_worktree: bool,
    keep_changes: bool,
) -> None:
    """Roll back an issue to an earlier stage.

    Archives output files from stages after the target stage and resets
    the issue state. Use this when an issue has gone down the wrong path
    and needs to be redone from an earlier point.

    Examples:
        agenttree rollback 085 research      # Roll back to research stage
        agenttree rollback 042 plan --yes    # Skip confirmation
        agenttree rollback 042 define --reset-worktree  # Also discard code changes
    """
    from datetime import datetime, timezone
    from agenttree.state import get_active_agent, unregister_agent
    import shutil
    import yaml as pyyaml

    # Block if in container
    if is_running_in_container():
        console.print("[red]Error: 'rollback' cannot be run from inside a container[/red]")
        console.print("[dim]This command is for human reviewers only.[/dim]")
        sys.exit(1)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"
    issue = get_issue_func(issue_id_normalized)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    # Load config and validate stage
    config = load_config()
    stage_names = config.get_stage_names()

    if stage_name not in stage_names:
        console.print(f"[red]Invalid stage: '{stage_name}'[/red]")
        console.print(f"[dim]Valid stages: {', '.join(stage_names)}[/dim]")
        sys.exit(1)

    # Check if target stage is before or same as current stage
    try:
        current_idx = stage_names.index(issue.stage)
        target_idx = stage_names.index(stage_name)
    except ValueError:
        console.print(f"[red]Issue is at unknown stage: {issue.stage}[/red]")
        sys.exit(1)

    if target_idx >= current_idx:
        console.print(f"[red]Cannot rollback: target stage '{stage_name}' is not before current stage '{issue.stage}'[/red]")
        console.print("[dim]Rollback is for going backwards in the workflow.[/dim]")
        sys.exit(1)

    # Cannot rollback to redirect_only stages (they're not in normal progression)
    target_stage_config = config.get_stage(stage_name)
    if target_stage_config and target_stage_config.redirect_only:
        console.print(f"[red]Cannot rollback to redirect-only stage '{stage_name}'[/red]")
        sys.exit(1)

    # Determine first substage of target stage
    target_substage = None
    if target_stage_config:
        substages = target_stage_config.substage_order()
        if substages:
            target_substage = substages[0]

    # Collect stages after target that will have output files archived
    stages_to_archive = stage_names[target_idx + 1 : current_idx + 1]

    # Collect output files from stages being rolled back
    files_to_archive: list[str] = []
    for stage in stages_to_archive:
        stage_config = config.get_stage(stage)
        if stage_config:
            # Stage-level output
            if stage_config.output:
                files_to_archive.append(stage_config.output)
            # Substage outputs
            for substage_config in stage_config.substages.values():
                if substage_config.output:
                    files_to_archive.append(substage_config.output)

    # Determine worktree reset behavior
    # Auto-reset if rolling back to before implement stage
    implement_idx = stage_names.index("implement") if "implement" in stage_names else -1
    auto_reset = target_idx < implement_idx if implement_idx >= 0 else False

    should_reset = reset_worktree or (auto_reset and not keep_changes)

    # Check for active agents (all roles)
    from agenttree.state import get_active_agents_for_issue
    active_agents = get_active_agents_for_issue(issue_id_normalized)
    active_agent = active_agents[0] if active_agents else None  # For worktree reference

    # Show confirmation
    issue_dir = get_issue_dir(issue_id_normalized)

    console.print(f"\n[bold]Rollback Issue #{issue.id}: {issue.title}[/bold]")
    console.print(f"\n  Current stage: [yellow]{issue.stage}[/yellow]")
    target_str = stage_name
    if target_substage:
        target_str += f".{target_substage}"
    console.print(f"  Target stage:  [green]{target_str}[/green]")

    if files_to_archive:
        console.print(f"\n  Files to archive:")
        for f in files_to_archive:
            file_path = issue_dir / f if issue_dir else Path(f)
            exists = " (exists)" if file_path.exists() else " (not found)"
            console.print(f"    - {f}{exists}")

    if active_agents:
        console.print(f"\n  [yellow]⚠ {len(active_agents)} active agent(s) will be unregistered[/yellow]")

    if should_reset:
        console.print(f"\n  [yellow]⚠ Worktree will be reset to origin/main[/yellow]")
    else:
        console.print(f"\n  [dim]Worktree changes will be preserved[/dim]")

    console.print()

    # Confirm unless --yes
    if not yes:
        if not click.confirm("Proceed with rollback?"):
            console.print("[yellow]Cancelled[/yellow]")
            return

    # === Execute rollback ===

    # 1. Archive output files
    if issue_dir and files_to_archive:
        archive_dir = issue_dir / "archive"
        archive_dir.mkdir(exist_ok=True)

        # Create timestamped subdirectory for this rollback
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rollback_dir = archive_dir / f"rollback_{timestamp}"
        rollback_dir.mkdir(exist_ok=True)

        archived_count = 0
        for filename in files_to_archive:
            src = issue_dir / filename
            if src.exists():
                dst = rollback_dir / filename
                shutil.move(str(src), str(dst))
                console.print(f"  [dim]Archived: {filename}[/dim]")
                archived_count += 1

        if archived_count > 0:
            console.print(f"[green]✓ Archived {archived_count} file(s) to archive/rollback_{timestamp}/[/green]")

    # 2. Update issue stage with rollback history entry
    if issue_dir:
        yaml_path = issue_dir / "issue.yaml"
        if yaml_path.exists():
            with open(yaml_path) as fh:
                data = pyyaml.safe_load(fh)

            # Update stage
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            data["stage"] = stage_name
            data["substage"] = target_substage
            data["updated"] = now

            # Add rollback history entry
            history_entry = {
                "stage": stage_name,
                "substage": target_substage,
                "timestamp": now,
                "type": "rollback",
            }
            if "history" not in data:
                data["history"] = []
            data["history"].append(history_entry)

            # Clear PR metadata (don't close the PR, just clear the reference)
            if "pr_number" in data:
                del data["pr_number"]
            if "pr_url" in data:
                del data["pr_url"]

            with open(yaml_path, "w") as fh:
                pyyaml.dump(data, fh, default_flow_style=False, sort_keys=False)

            console.print(f"[green]✓ Issue stage set to {target_str}[/green]")

    # 3. Clear agent session
    delete_session(issue_id_normalized)
    console.print("[green]✓ Cleared agent session[/green]")

    # 4. Unregister all active agents (if any)
    if active_agents:
        from agenttree.state import unregister_all_agents_for_issue
        unregister_all_agents_for_issue(issue_id_normalized)
        console.print(f"[green]✓ Unregistered {len(active_agents)} active agent(s)[/green]")

    # 5. Reset worktree if requested
    if should_reset and active_agent:
        worktree_path = active_agent.worktree
        if worktree_path.exists():
            try:
                subprocess.run(
                    ["git", "reset", "--hard", "origin/main"],
                    cwd=worktree_path,
                    capture_output=True,
                    check=True,
                )
                console.print(f"[green]✓ Reset worktree to origin/main[/green]")
            except subprocess.CalledProcessError as e:
                console.print(f"[yellow]Warning: Failed to reset worktree: {e}[/yellow]")

    # 6. Sync changes
    from agenttree.agents_repo import sync_agents_repo
    from agenttree.issues import get_agenttree_path
    agents_path = get_agenttree_path()
    sync_agents_repo(agents_path, pull_only=False, commit_message=f"Rollback issue {issue_id} to {stage_name}")

    console.print(f"\n[green]✓ Issue #{issue.id} rolled back to {target_str}[/green]")
    if active_agent:
        console.print(f"\n[dim]Restart the agent when ready:[/dim]")
        console.print(f"  agenttree start {issue.id}")


@main.command("cleanup")
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
    help="Ask manager AI to review edge cases before cleanup"
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
        agenttree cleanup --ai-review        # Ask manager AI about edge cases
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
            except Exception:
                pass

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
        console.print("[bold]Asking manager AI to review edge cases...[/bold]")
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
    """Ask the manager AI to review cleanup edge cases.

    Args:
        edge_cases: List of edge case dictionaries
        config: AgentTree configuration
    """
    from agenttree.tmux import session_exists, send_keys

    manager_session = f"{config.project}-manager"

    if not session_exists(manager_session):
        console.print("[yellow]Manager agent not running - skipping AI review[/yellow]")
        console.print("[dim]Start the manager with: agenttree start 0[/dim]")
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

    console.print("[dim]Sending to manager for review...[/dim]")
    send_keys(manager_session, prompt + "\n")
    console.print(f"[cyan]Sent edge cases to manager. Check tmux session '{manager_session}' for response.[/cyan]")


@main.command("tui")
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


if __name__ == "__main__":
    main()
