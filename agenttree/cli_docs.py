"""CLI commands for creating agent documentation.

Provides specialized commands for creating different document types:
- create-rfc: Design proposals with auto-numbering
- create-investigation: Bug investigations with severity tracking
- create-note: Informal notes and learnings
- complete: Finalize task and update context summary
"""

import os
import subprocess
from pathlib import Path
from datetime import datetime
import click
from rich.console import Console

from agenttree.frontmatter import (
    create_frontmatter,
    get_git_context,
    utc_now,
    get_commits_since,
    add_frontmatter_fields,
)
from agenttree.agents_repo import slugify

console = Console()


def get_next_rfc_number(agents_path: Path) -> int:
    """Get next available RFC number by scanning existing RFCs.

    Args:
        agents_path: Path to agents/ repository

    Returns:
        Next RFC number (e.g., 1, 2, 3...)
    """
    rfcs_dir = agents_path / "rfcs"
    if not rfcs_dir.exists():
        return 1

    max_num = 0
    for rfc_file in rfcs_dir.glob("*.md"):
        # Parse RFC-001-title.md -> 1
        try:
            num_str = rfc_file.stem.split("-")[0]
            if num_str.startswith("RFC"):
                num_str = num_str[3:]
            num = int(num_str)
            max_num = max(max_num, num)
        except (ValueError, IndexError):
            continue

    return max_num + 1


def open_editor(file_path: Path) -> bool:
    """Open file in user's default editor.

    Args:
        file_path: Path to file to edit

    Returns:
        True if editing succeeded, False otherwise
    """
    editor = os.environ.get("EDITOR", "vim")

    try:
        result = subprocess.run([editor, str(file_path)])
        return result.returncode == 0
    except FileNotFoundError:
        console.print(f"[yellow]Editor '{editor}' not found. File created at: {file_path}[/yellow]")
        console.print(f"[yellow]Edit it manually and commit to agents/ repo[/yellow]")
        return False


def get_current_task_info(agents_path: Path, agent_num: int) -> dict:
    """Get info about agent's current task.

    Args:
        agents_path: Path to agents/ repository
        agent_num: Agent number

    Returns:
        Dict with task_log path, issue_number, etc. (or empty dict if no current task)
    """
    task_dir = agents_path / "tasks" / f"agent-{agent_num}"
    if not task_dir.exists():
        return {}

    # Get most recent task file
    task_files = sorted(task_dir.glob("*.md"), reverse=True)
    if not task_files:
        return {}

    task_file = task_files[0]

    # Try to parse frontmatter to get issue number
    try:
        from agenttree.frontmatter import parse_frontmatter
        content = task_file.read_text()
        frontmatter, _ = parse_frontmatter(content)

        return {
            "task_log": str(task_file.relative_to(agents_path)),
            "issue_number": frontmatter.get("issue_number"),
            "task_id": frontmatter.get("task_id"),
        }
    except Exception:
        return {"task_log": str(task_file.relative_to(agents_path))}


@click.command("create-rfc")
@click.argument("title")
@click.option("--related-issue", type=int, help="Related GitHub issue number")
@click.option(
    "--complexity",
    type=click.Choice(["high", "medium", "low"]),
    default="medium",
    help="Complexity level",
)
def create_rfc(title: str, related_issue: int, complexity: str):
    """Create an RFC (Request for Comments) design proposal.

    RFCs are automatically numbered (scans existing RFCs for next number).

    Examples:
        agenttree create-rfc "Add OAuth2 support" --related-issue 42
        agenttree create-rfc "Redesign database schema" --complexity high
    """
    repo_path = Path.cwd()
    agents_path = repo_path / "agents"

    if not agents_path.exists():
        console.print("[red]Error: agents/ repository not found[/red]")
        console.print("[yellow]Run 'agenttree init' first[/yellow]")
        return

    # Get agent number from environment
    agent_num = os.getenv("AGENT_NUM")
    if not agent_num:
        console.print("[yellow]Warning: AGENT_NUM not set, using 'unknown'[/yellow]")
        author = "unknown"
    else:
        author = f"agent-{agent_num}"

    # Auto-number RFC
    rfc_number = get_next_rfc_number(agents_path)
    slug = slugify(title)

    rfcs_dir = agents_path / "rfcs"
    rfcs_dir.mkdir(exist_ok=True)

    rfc_file = rfcs_dir / f"{rfc_number:03d}-{slug}.md"

    if rfc_file.exists():
        console.print(f"[red]Error: RFC file already exists: {rfc_file}[/red]")
        return

    # Get git context
    git_ctx = get_git_context(repo_path)

    # Get current task info
    task_info = get_current_task_info(agents_path, int(agent_num)) if agent_num else {}

    # Create frontmatter
    frontmatter = {
        "document_type": "rfc",
        "version": 1,
        "rfc_number": rfc_number,
        "title": title,
        "author": author,
        "status": "proposed",
        "proposed_at": utc_now(),
        "decided_at": None,
        "implemented_at": None,
        "decision_maker": None,
        "decision_rationale": None,
        **git_ctx,
        "implemented_in_prs": [],
        "superseded_by": None,
        "related_rfcs": [],
        "related_specs": [],
        "tasks": [task_info.get("task_log")] if task_info.get("task_log") else [],
        "related_issue": related_issue,
        "complexity": complexity,
        "tags": [],
    }

    # Create content with template
    content = create_frontmatter(frontmatter)
    content += f"# RFC-{rfc_number:03d}: {title}\n\n"
    content += f"## Summary\n\n"
    content += f"<!-- 2-3 sentences: what you're proposing -->\n\n"
    content += f"## Motivation\n\n"
    content += f"**Current State:**\n"
    content += f"<!-- What exists now -->\n\n"
    content += f"**Problem:**\n"
    content += f"<!-- What's wrong with current state -->\n\n"
    content += f"**Proposed Solution:**\n"
    content += f"<!-- High-level approach -->\n\n"
    content += f"## Detailed Design\n\n"
    content += f"<!-- How it works - diagrams, pseudocode, API designs -->\n\n"
    content += f"## Drawbacks\n\n"
    content += f"<!-- Why we might NOT do this -->\n\n"
    content += f"## Alternatives Considered\n\n"
    content += f"### Option 1: {{Name}}\n"
    content += f"- **Pros:**\n"
    content += f"- **Cons:**\n"
    content += f"- **Why not chosen:**\n\n"
    content += f"## Unresolved Questions\n\n"
    content += f"- [ ] Question 1\n"
    content += f"- [ ] Question 2\n\n"

    rfc_file.write_text(content)

    console.print(f"[green]✓ Created RFC-{rfc_number:03d}: {title}[/green]")
    console.print(f"[dim]  File: {rfc_file}[/dim]")

    # Open in editor
    console.print(f"\n[cyan]Opening in editor...[/cyan]")
    if open_editor(rfc_file):
        console.print(f"[green]✓ RFC saved[/green]")
        console.print(f"\n[yellow]Don't forget to commit to agents/ repo:[/yellow]")
        console.print(f"  cd agents")
        console.print(f"  git add {rfc_file.relative_to(agents_path)}")
        console.print(f"  git commit -m 'Add RFC-{rfc_number:03d}: {title}'")
        console.print(f"  git push")


@click.command("create-investigation")
@click.argument("title")
@click.option("--issue", type=int, required=True, help="GitHub issue number")
@click.option(
    "--severity",
    type=click.Choice(["critical", "high", "medium", "low"]),
    default="medium",
    help="Severity level",
)
def create_investigation(title: str, issue: int, severity: str):
    """Create an investigation document for bug analysis.

    Investigations track the process of debugging an issue.

    Examples:
        agenttree create-investigation "Race condition in session store" --issue 45 --severity critical
        agenttree create-investigation "Memory leak in worker" --issue 50 --severity high
    """
    repo_path = Path.cwd()
    agents_path = repo_path / "agents"

    if not agents_path.exists():
        console.print("[red]Error: agents/ repository not found[/red]")
        console.print("[yellow]Run 'agenttree init' first[/yellow]")
        return

    # Get agent number from environment
    agent_num = os.getenv("AGENT_NUM")
    if not agent_num:
        console.print("[yellow]Warning: AGENT_NUM not set, using 'unknown'[/yellow]")
        investigator = "unknown"
    else:
        investigator = f"agent-{agent_num}"

    # Create filename
    date = datetime.now().strftime("%Y-%m-%d")
    slug = slugify(title)

    investigations_dir = agents_path / "investigations"
    investigations_dir.mkdir(exist_ok=True)

    investigation_file = investigations_dir / f"{date}-{slug}.md"

    if investigation_file.exists():
        console.print(f"[red]Error: Investigation file already exists: {investigation_file}[/red]")
        return

    # Get git context
    git_ctx = get_git_context(repo_path)

    # Get current task info
    task_info = get_current_task_info(agents_path, int(agent_num)) if agent_num else {}

    # Create frontmatter
    frontmatter = {
        "document_type": "investigation",
        "version": 1,
        "title": title,
        "investigator": investigator,
        "status": "investigating",
        "started_at": utc_now(),
        "resolved_at": None,
        "issue_number": issue,
        "issue_url": f"https://github.com/{git_ctx.get('repo_url', '').split('/')[-2:]}/issues/{issue}" if git_ctx.get("repo_url") else None,
        "severity": severity,
        **git_ctx,
        "affected_files": [],
        "root_cause_commit": None,
        "root_cause_file": None,
        "root_cause_line": None,
        "fixed_in_pr": None,
        "fixed_in_commits": [],
        "related_investigations": [],
        "related_tasks": [task_info.get("task_log")] if task_info.get("task_log") else [],
        "tags": [],
    }

    # Create content with template
    content = create_frontmatter(frontmatter)
    content += f"# Investigation: {title}\n\n"
    content += f"## Problem\n\n"
    content += f"<!-- What's broken or unclear -->\n\n"
    content += f"## Hypothesis\n\n"
    content += f"<!-- What you think is causing it -->\n\n"
    content += f"## Investigation Steps\n\n"
    content += f"### Step 1: {{Description}}\n"
    content += f"**What:** <!-- What you did -->\n"
    content += f"**Result:** <!-- What you found -->\n\n"
    content += f"### Step 2: {{Description}}\n"
    content += f"**What:** <!-- What you did -->\n"
    content += f"**Result:** <!-- What you found -->\n\n"
    content += f"## Root Cause\n\n"
    content += f"<!-- What actually caused the issue -->\n\n"
    content += f"## Solution\n\n"
    content += f"<!-- How to fix it -->\n\n"
    content += f"## Prevention\n\n"
    content += f"<!-- How to prevent this in the future -->\n\n"

    investigation_file.write_text(content)

    console.print(f"[green]✓ Created investigation: {title}[/green]")
    console.print(f"[dim]  File: {investigation_file}[/dim]")

    # Open in editor
    console.print(f"\n[cyan]Opening in editor...[/cyan]")
    if open_editor(investigation_file):
        console.print(f"[green]✓ Investigation saved[/green]")
        console.print(f"\n[yellow]Don't forget to commit to agents/ repo:[/yellow]")
        console.print(f"  cd agents")
        console.print(f"  git add {investigation_file.relative_to(agents_path)}")
        console.print(f"  git commit -m 'Add investigation: {title}'")
        console.print(f"  git push")


@click.command("create-note")
@click.argument("title")
@click.option(
    "--type",
    type=click.Choice(["gotcha", "pattern", "tip", "question"]),
    default="tip",
    help="Note type",
)
@click.option("--tags", help="Comma-separated tags")
@click.option("--applies-to", help="File this note applies to")
@click.option(
    "--severity",
    type=click.Choice(["important", "nice_to_know"]),
    default="nice_to_know",
    help="Severity (for gotchas)",
)
def create_note(title: str, type: str, tags: str, applies_to: str, severity: str):
    """Create a note with auto-populated frontmatter.

    Examples:
        agenttree create-note "JWT token expiry gotcha" --type gotcha --tags auth,jwt
        agenttree create-note "API retry pattern" --type pattern --tags api,resilience
        agenttree create-note "Remember to check CORS" --type tip
    """
    repo_path = Path.cwd()
    agents_path = repo_path / "agents"

    if not agents_path.exists():
        console.print("[red]Error: agents/ repository not found[/red]")
        console.print("[yellow]Run 'agenttree init' first[/yellow]")
        return

    # Get agent number from environment
    agent_num = os.getenv("AGENT_NUM")
    if not agent_num:
        console.print("[yellow]Warning: AGENT_NUM not set, using 'unknown'[/yellow]")
        author = "unknown"
        notes_dir = agents_path / "notes" / "unknown"
    else:
        author = f"agent-{agent_num}"
        notes_dir = agents_path / "notes" / f"agent-{agent_num}"

    notes_dir.mkdir(parents=True, exist_ok=True)

    # Create filename
    slug = slugify(title)
    note_file = notes_dir / f"{slug}.md"

    if note_file.exists():
        console.print(f"[red]Error: Note file already exists: {note_file}[/red]")
        return

    # Get git context
    git_ctx = get_git_context(repo_path)

    # Get current task info
    task_info = get_current_task_info(agents_path, int(agent_num)) if agent_num else {}

    # Create frontmatter
    frontmatter = {
        "document_type": "note",
        "version": 1,
        "note_type": type,
        "title": title,
        "author": author,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "discovered_in_task": task_info.get("task_log"),
        "issue_number": task_info.get("issue_number"),
        **git_ctx,
        "applies_to_files": [applies_to] if applies_to else [],
        "severity": severity if type == "gotcha" else None,
        "related_notes": [],
        "related_specs": [],
        "tags": tags.split(",") if tags else [],
    }

    # Create content
    content = create_frontmatter(frontmatter)
    content += f"# {title}\n\n"
    content += f"<!-- Write your note here -->\n\n"

    note_file.write_text(content)

    console.print(f"[green]✓ Created note: {title}[/green]")
    console.print(f"[dim]  File: {note_file}[/dim]")

    # Open in editor
    console.print(f"\n[cyan]Opening in editor...[/cyan]")
    if open_editor(note_file):
        console.print(f"[green]✓ Note saved[/green]")
        console.print(f"\n[yellow]Don't forget to commit to agents/ repo:[/yellow]")
        console.print(f"  cd agents")
        console.print(f"  git add {note_file.relative_to(agents_path)}")
        console.print(f"  git commit -m '{author}: Add note on {title}'")
        console.print(f"  git push")


@click.command("complete")
@click.argument("agent_num", type=int)
@click.option("--pr", type=int, help="PR number created")
@click.option("--skip-summary", is_flag=True, help="Skip updating context summary")
def complete(agent_num: int, pr: int, skip_summary: bool):
    """Mark task as complete and update context summary.

    This command:
    1. Finds the current task for the agent
    2. Updates task log frontmatter with completion time, commits, PR
    3. Opens context summary for agent to fill in final details

    Examples:
        agenttree complete 1 --pr 50
        agenttree complete 2  # No PR yet
    """
    repo_path = Path.cwd()
    agents_path = repo_path / "agents"

    if not agents_path.exists():
        console.print("[red]Error: agents/ repository not found[/red]")
        return

    # Find current task
    task_dir = agents_path / "tasks" / f"agent-{agent_num}"
    if not task_dir.exists():
        console.print(f"[red]Error: No tasks found for agent-{agent_num}[/red]")
        return

    task_files = sorted(task_dir.glob("*.md"), reverse=True)
    if not task_files:
        console.print(f"[red]Error: No task files found for agent-{agent_num}[/red]")
        return

    task_file = task_files[0]

    # Parse frontmatter
    from agenttree.frontmatter import parse_frontmatter
    content = task_file.read_text()
    frontmatter_data, markdown = parse_frontmatter(content)

    if not frontmatter_data:
        console.print(f"[red]Error: No frontmatter found in {task_file}[/red]")
        return

    # Get starting commit to calculate commits made
    starting_commit = frontmatter_data.get("starting_commit")
    if starting_commit:
        commits = get_commits_since(repo_path, starting_commit)
        commits_data = [{"hash": c["hash"], "message": c["message"], "timestamp": c["timestamp"]} for c in commits]
    else:
        commits_data = []

    # Update frontmatter
    updates = {
        "completed_at": utc_now(),
        "status": "completed",
        "commits": commits_data,
    }

    if pr:
        # Construct PR URL from repo_url
        repo_url = frontmatter_data.get("repo_url")
        if repo_url:
            pr_url = f"{repo_url}/pull/{pr}"
        else:
            pr_url = None

        updates.update({
            "pr_number": pr,
            "pr_url": pr_url,
            "pr_status": "open",
        })

    add_frontmatter_fields(task_file, updates)

    console.print(f"[green]✓ Updated task log: {task_file.name}[/green]")
    if commits_data:
        console.print(f"[dim]  Added {len(commits_data)} commits to frontmatter[/dim]")

    # Update context summary
    if not skip_summary:
        issue_num = frontmatter_data.get("issue_number")
        if issue_num:
            context_file = agents_path / "context" / f"agent-{agent_num}" / f"issue-{issue_num}.md"

            if context_file.exists():
                # Update context summary frontmatter
                updates = {
                    "summary_created": utc_now(),
                    "final_commit": commits_data[-1]["hash"] if commits_data else None,
                    "pr_number": pr,
                    "pr_status": "open" if pr else None,
                    "commits_count": len(commits_data),
                }

                add_frontmatter_fields(context_file, updates)

                console.print(f"\n[cyan]Opening context summary for final review...[/cyan]")
                console.print(f"[dim]Fill in the sections if you haven't already:[/dim]")
                console.print(f"[dim]  - What Was Done[/dim]")
                console.print(f"[dim]  - Key Decisions[/dim]")
                console.print(f"[dim]  - Gotchas Discovered[/dim]")
                console.print(f"[dim]  - For Resuming[/dim]")

                if open_editor(context_file):
                    console.print(f"[green]✓ Context summary updated[/green]")
            else:
                console.print(f"[yellow]Warning: Context summary not found: {context_file}[/yellow]")

    console.print(f"\n[yellow]Don't forget to commit to agents/ repo:[/yellow]")
    console.print(f"  cd agents")
    console.print(f"  git add .")
    console.print(f"  git commit -m 'agent-{agent_num}: Complete task'")
    console.print(f"  git push")


@click.command("resume")
@click.argument("agent_num", type=int)
@click.option("--task", "task_num", type=int, help="Issue number to resume")
@click.option("--pr", type=int, help="PR number to resume")
def resume(agent_num: int, task_num: int, pr: int):
    """Resume work on a previous task.

    This command:
    1. Finds the task/PR to resume
    2. Checks out the work branch
    3. Loads context summary into TASK.md
    4. Agent can continue where they left off

    Examples:
        agenttree resume 1 --task 42    # Resume work on issue #42
        agenttree resume 1 --pr 50      # Resume work on PR #50
    """
    from agenttree.config import load_config
    from agenttree.frontmatter import parse_frontmatter

    repo_path = Path.cwd()
    config = load_config(repo_path)
    agents_path = repo_path / "agents"

    if not agents_path.exists():
        console.print("[red]Error: agents/ repository not found[/red]")
        return

    if not task_num and not pr:
        console.print("[red]Error: Provide either --task or --pr[/red]")
        return

    # Find the task
    task_dir = agents_path / "tasks" / f"agent-{agent_num}"
    if not task_dir.exists():
        console.print(f"[red]Error: No tasks found for agent-{agent_num}[/red]")
        return

    # Search for task by issue number or PR
    task_file = None
    for tf in task_dir.glob("*.md"):
        content = tf.read_text()
        fm, _ = parse_frontmatter(content)

        if task_num and fm.get("issue_number") == task_num:
            task_file = tf
            break
        elif pr and fm.get("pr_number") == pr:
            task_file = tf
            break

    if not task_file:
        console.print(f"[red]Error: Task not found for issue #{task_num} or PR #{pr}[/red]")
        return

    # Load frontmatter
    content = task_file.read_text()
    frontmatter_data, _ = parse_frontmatter(content)

    work_branch = frontmatter_data.get("work_branch")
    issue_number = frontmatter_data.get("issue_number")
    pr_number = frontmatter_data.get("pr_number")

    console.print(f"\n[cyan]Resuming task: {frontmatter_data.get('issue_title')}[/cyan]")
    console.print(f"[dim]Issue: #{issue_number}[/dim]")
    if pr_number:
        console.print(f"[dim]PR: #{pr_number}[/dim]")
    console.print(f"[dim]Branch: {work_branch}[/dim]")

    # Get worktree path
    worktree_path = config.get_worktree_path(agent_num)

    if not worktree_path.exists():
        console.print(f"[red]Error: Agent {agent_num} worktree not found[/red]")
        console.print(f"[yellow]Run: agenttree setup {agent_num}[/yellow]")
        return

    # Checkout the work branch
    console.print(f"\n[cyan]Checking out branch: {work_branch}[/cyan]")
    try:
        subprocess.run(
            ["git", "checkout", work_branch],
            cwd=worktree_path,
            check=True,
            capture_output=True
        )
        console.print(f"[green]✓ Checked out {work_branch}[/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error checking out branch: {e.stderr.decode()}[/red]")
        return

    # Load context summary
    if issue_number:
        context_file = agents_path / "context" / f"agent-{agent_num}" / f"issue-{issue_number}.md"

        if context_file.exists():
            context_content = context_file.read_text()
            context_fm, context_md = parse_frontmatter(context_content)

            # Create TASK.md with context
            task_md_path = worktree_path / "TASK.md"

            task_content = f"# Resume Task: {frontmatter_data.get('issue_title')}\n\n"
            task_content += f"**Resuming work from:** {frontmatter_data.get('started_at')}\n"
            task_content += f"**Issue:** #{issue_number}\n"
            if pr_number:
                task_content += f"**PR:** #{pr_number} ({frontmatter_data.get('pr_url')})\n"
            task_content += f"**Branch:** {work_branch}\n\n"
            task_content += f"## Previous Context\n\n"
            task_content += context_md
            task_content += f"\n\n## Continue Working\n\n"
            task_content += f"<!-- Add new work log entries here -->\n"

            task_md_path.write_text(task_content)

            console.print(f"\n[green]✓ Created TASK.md with context summary[/green]")
            console.print(f"[dim]  Read TASK.md to see what was done previously[/dim]")
        else:
            console.print(f"[yellow]Warning: Context summary not found, creating minimal TASK.md[/yellow]")

            task_md_path = worktree_path / "TASK.md"
            task_content = f"# Resume Task: {frontmatter_data.get('issue_title')}\n\n"
            task_content += f"**Issue:** #{issue_number}\n"
            if pr_number:
                task_content += f"**PR:** #{pr_number}\n"
            task_content += f"\n## Task Log\n\n"
            task_content += f"See: {task_file.relative_to(agents_path)}\n"

            task_md_path.write_text(task_content)

    console.print(f"\n[green]✓ Ready to resume work on agent-{agent_num}[/green]")
    console.print(f"\n[cyan]Next steps:[/cyan]")
    console.print(f"  1. Read TASK.md for context")
    console.print(f"  2. Review commits: git log")
    console.print(f"  3. Continue work")
    console.print(f"  4. Commit and push when done")
