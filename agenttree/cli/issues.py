"""Issue management commands (create, list, show, doc, check-deps)."""

import sys
from pathlib import Path

import click
from rich.table import Table

from agenttree.cli._utils import console, load_config, get_issue_func, get_issue_dir, normalize_issue_id
from agenttree.issues import (
    Priority,
    create_issue as create_issue_func,
    list_issues as list_issues_func,
    get_issue_context,
    check_dependencies_met,
    get_ready_issues,
    update_issue_priority,
)


@click.group()
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
@click.option(
    "--needs-ui-review",
    is_flag=True,
    help="If set, ui_review stage will run for this issue"
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
    context: str | None,
    solutions: str | None,
    depends_on: tuple,
    no_start: bool,
    needs_ui_review: bool,
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
    # Import start_agent here to avoid circular imports
    from agenttree.cli.agents import start_agent

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
            dep_num = normalize_issue_id(dep)
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
            needs_ui_review=needs_ui_review,
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
def issue_list(stage: str | None, priority: str | None, as_json: bool) -> None:
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
def issue_show(issue_id: str, as_json: bool, field_name: str | None) -> None:
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
    console.print(f"[bold]Stage:[/bold] {issue.stage}")

    console.print(f"[bold]Priority:[/bold] {issue.priority.value}")

    if issue.labels:
        console.print(f"[bold]Labels:[/bold] {', '.join(issue.labels)}")

    if issue.dependencies:
        all_met, unmet = check_dependencies_met(issue)
        deps_str = ", ".join(issue.dependencies)
        if all_met:
            console.print(f"[bold]Dependencies:[/bold] {deps_str} [green](all met)[/green]")
        else:
            console.print(f"[bold]Dependencies:[/bold] {deps_str} [yellow](waiting on: {', '.join(unmet)})[/yellow]")

    if issue.branch:
        console.print(f"[bold]Branch:[/bold] {issue.branch}")

    if issue.pr_number:
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
            agent_str = f" (agent {entry.agent})" if entry.agent else ""
            console.print(f"  • {entry.timestamp[:10]} → {entry.stage}{agent_str}")

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
