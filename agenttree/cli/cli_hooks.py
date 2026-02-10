"""Hook management commands."""

import sys

import click

from agenttree.cli._utils import console, get_issue_func, normalize_issue_id
from agenttree.config import load_config
from agenttree.hooks import parse_hook, is_running_in_container
from agenttree.issues import get_next_stage


@click.group("hooks")
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
    # Normalize issue ID
    issue_id_normalized = normalize_issue_id(issue_id)
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
                param_str = f"{params.get('file', '')} -> {params.get('section', '')} ({params.get('expect', '')})"
            elif hook_type == "field_check":
                param_str = f"{params.get('file', '')} -> {params.get('path', '')} (min: {params.get('min', 'n/a')})"
            elif hook_type == "create_file":
                param_str = f"{params.get('template', '')} -> {params.get('dest', '')}"
            else:
                param_str = str(params) if params else ""

            console.print(f"  - [green]{hook_type}[/green]: {param_str}{optional_str}{skipped}")

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
