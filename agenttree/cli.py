"""CLI for AgentTree."""

import subprocess
import sys
from pathlib import Path
from typing import Optional
import click
from rich.console import Console
from rich.table import Table

from agenttree.config import load_config
from agenttree.worktree import WorktreeManager
from agenttree.tmux import TmuxManager
from agenttree.github import GitHubManager, get_issue as get_github_issue, ensure_gh_cli
from agenttree.container import get_container_runtime
from agenttree.agents_repo import AgentsRepository
from agenttree.cli_docs import create_rfc, create_investigation, create_note, complete, resume
from agenttree.issues import (
    Issue,
    Stage,
    Priority,
    HUMAN_REVIEW_STAGES,
    create_issue as create_issue_func,
    list_issues as list_issues_func,
    get_issue as get_issue_func,
    get_issue_dir,
    get_next_stage,
    update_issue_stage,
    load_skill,
)

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
    repo_path = Path.cwd()

    # Check if we're in a git repo
    if not (repo_path / ".git").exists():
        console.print("[red]Error: Not a git repository[/red]")
        sys.exit(1)

    config_file = repo_path / ".agenttree.yaml"

    if config_file.exists():
        console.print("[yellow]Warning: .agenttree.yaml already exists[/yellow]")
        if not click.confirm("Overwrite?"):
            return

    # Determine project name
    if not project:
        project = repo_path.name

    # Create config
    config_data = {
        "project": project,
        "worktrees_dir": worktrees_dir or ".worktrees",
        "port_range": "9001-9099",  # Less conflicting range (9000 + agent number)
        "default_tool": "claude",
        "tools": {
            "claude": {
                "command": "claude",
                "startup_prompt": "Check TASK.md and start working on it.",
            },
            "aider": {
                "command": "aider --model sonnet",
                "startup_prompt": "/read TASK.md",
            },
        },
    }

    import yaml

    with open(config_file, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False)

    console.print(f"[green]✓ Created {config_file}[/green]")

    # Create .agenttrees/scripts directory
    scripts_dir = repo_path / ".agenttrees" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    # Create worktree-setup.sh template
    setup_script = scripts_dir / "worktree-setup.sh"
    setup_template = """#!/bin/bash
# AgentTree Worktree Setup Script
#
# 🤖 AI AGENT: This script runs when setting up your worktree.
# If you encounter errors on your first task, this script likely needs customization.
# Feel free to modify it based on errors you see - future agents will benefit!
#
# This script receives three arguments:
#   $1 = WORKTREE_PATH (e.g., ~/Projects/worktrees/myapp/agent-1)
#   $2 = AGENT_NUM (e.g., 1, 2, 3)  ← YOUR AGENT IDENTITY
#   $3 = AGENT_PORT (e.g., 9001, 9002, 9003)
#
# After setup, you can access your identity via:
#   - Environment variable: $AGENT_NUM
#   - .env file: AGENT_NUM=1

set -e  # Exit on error

WORKTREE_PATH="$1"
AGENT_NUM="$2"
AGENT_PORT="$3"

echo "🔧 Setting up agent-$AGENT_NUM at $WORKTREE_PATH"
cd "$WORKTREE_PATH"

# ============================================================================
# ENVIRONMENT FILES - Customize based on your project's needs
# ============================================================================

# Basic .env copy (works for most projects)
if [ -f "../.env" ]; then
    cp ../.env .env
    echo "✓ Copied .env"
fi

# 🤖 AI: If you need multiple env files, add them here:
# cp ../.env.local .env.local
# cp ../.env.test .env.test

# Set agent-specific PORT and AGENT_NUM to avoid conflicts
if [ -f ".env" ]; then
    # Remove existing lines and add new ones
    sed -i.bak '/^PORT=/d' .env
    sed -i.bak '/^AGENT_NUM=/d' .env
    echo "PORT=$AGENT_PORT" >> .env
    echo "AGENT_NUM=$AGENT_NUM" >> .env
    rm .env.bak 2>/dev/null || true
    echo "✓ Set PORT=$AGENT_PORT and AGENT_NUM=$AGENT_NUM in .env"
else
    echo "PORT=$AGENT_PORT" > .env
    echo "AGENT_NUM=$AGENT_NUM" >> .env
    echo "✓ Created .env with PORT=$AGENT_PORT and AGENT_NUM=$AGENT_NUM"
fi

# ============================================================================
# DEPENDENCIES - Uncomment what your project uses
# ============================================================================

# 🤖 AI: If you see "command not found" or import errors, uncomment these:

# Node.js projects:
# npm install

# Python projects:
# pip install -r requirements.txt
# poetry install
# pipenv install

# Ruby projects:
# bundle install

# ============================================================================
# DATABASE - Only if your project needs it
# ============================================================================

# 🤖 AI: If you see database connection errors, uncomment these:

# Django:
# python manage.py migrate

# Rails:
# rails db:migrate

# Node.js:
# npm run db:migrate
# npx prisma migrate deploy

# ============================================================================
# BUILD STEPS - Only if your project needs compilation
# ============================================================================

# 🤖 AI: If you see "module not found" or build errors, uncomment these:

# npm run build
# make build
# cargo build

# ============================================================================
# AGENT-SPECIFIC CONFIG - For multi-agent isolation
# ============================================================================

# 🤖 AI: If agents interfere with each other, set unique values:

# Unique Redis instance per agent:
# echo "REDIS_URL=redis://localhost:600$AGENT_NUM" >> .env

# Unique database per agent:
# echo "DATABASE_NAME=myapp_agent_$AGENT_NUM" >> .env

# Unique directories:
# mkdir -p logs tmp uploads

# ============================================================================
# AGENT IDENTITY - Know yourself!
# ============================================================================

# Copy AGENT_GUIDE.md to worktree (with AGENT_NUM substitution)
if [ -f "../.agenttrees/templates/AGENT_GUIDE.md" ]; then
    sed "s/\${AGENT_NUM}/$AGENT_NUM/g; s/\${PORT}/$AGENT_PORT/g" ../.agenttrees/templates/AGENT_GUIDE.md > AGENT_GUIDE.md
    echo "✓ Created personalized AGENT_GUIDE.md"
fi

echo ""
echo "✅ Agent-$AGENT_NUM setup complete!"
echo ""
echo "📝 Your identity:"
echo "   AGENT_NUM: $AGENT_NUM"
echo "   PORT: $AGENT_PORT"
echo "   Your notes: .agenttrees/tasks/agent-$AGENT_NUM/"
echo ""
echo "📖 IMPORTANT: Read AGENT_GUIDE.md in your worktree to learn:"
echo "   - How to collaborate with other agents"
echo "   - Where to find task files and documentation"
echo "   - Best practices and troubleshooting"
echo ""
echo "🤖 To check your agent number at any time:"
echo "   echo \$AGENT_NUM"
echo "   cat .env | grep AGENT_NUM"
echo ""
echo "🤖 AI NOTE: If this setup didn't work for you, please improve this script"
echo "and push the changes so future agents can benefit!"
"""

    with open(setup_script, "w") as f:
        f.write(setup_template)

    # Make it executable
    import stat
    setup_script.chmod(setup_script.stat().st_mode | stat.S_IEXEC)

    console.print(f"[green]✓ Created {setup_script}[/green]")
    console.print(f"[dim]  → Customize this script for your project's setup needs[/dim]")

    # Create AGENT_GUIDE.md template
    templates_dir = repo_path / ".agenttrees" / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    agent_guide = templates_dir / "AGENT_GUIDE.md"
    agent_guide_template = """# AgentTree Agent Guide

Welcome, Agent! 👋

This guide helps you understand the AgentTree system and collaborate with other agents.

## Who Am I?

You can find your identity in the following ways:

```bash
# Your agent number
echo $AGENT_NUM

# Check your .env file
cat .env | grep AGENT_NUM

# Your assigned port
echo $PORT
```

**Your agent number is:** Agent-${AGENT_NUM}

## Project Structure

```
<project-root>/
├── .agenttrees/                ← Shared repo (issues, skills, scripts)
│   ├── issues/                 ← Issue tracking
│   │   └── 001-fix-login/
│   │       ├── issue.yaml
│   │       ├── problem.md
│   │       └── plan.md
│   ├── skills/                 ← Stage instructions
│   │   ├── problem.md
│   │   ├── research.md
│   │   └── implement.md
│   ├── scripts/                ← Setup scripts
│   │   └── worktree-setup.sh
│   └── templates/              ← Document templates
│       ├── AGENT_GUIDE.md      ← You are here!
│       └── problem.md
├── .worktrees/                 ← Agent worktrees (git ignored)
│   ├── agenttree-agent-1/
│   └── agenttree-agent-<N>/
└── <project files>
```

## Workflow

### 1. You Receive a Task

When dispatched, you'll find:
- **TASK.md** in your worktree root
- **.agenttrees/specs/issue-<num>.md** with the full specification
- **.agenttrees/tasks/agent-${AGENT_NUM}/<timestamp>-issue-<num>.md** your task log

### 2. You Work on It

- Read TASK.md first
- Check .agenttrees/specs/ for detailed requirements
- Look at .agenttrees/notes/ to see what other agents have learned
- Write code, run tests, fix bugs
- Commit your changes regularly

### 3. You Document Your Work

Create notes for other agents:

```bash
# Create a note about your findings
cat > .agenttrees/notes/agent-${AGENT_NUM}/api-authentication.md <<EOF
# API Authentication Pattern

I discovered that our API uses JWT tokens stored in localStorage.

## Key Files
- src/auth/jwt.ts - Token management
- src/api/client.ts - API client with auth headers

## Common Issues
- Tokens expire after 1 hour
- Refresh tokens are in cookies (not localStorage)

## Solution Pattern
Always check token expiry before API calls.
EOF

git -C .agenttrees add .
git -C .agenttrees commit -m "agent-${AGENT_NUM}: Document API auth pattern"
git -C .agenttrees push
```

### 4. You Collaborate

**Reading other agents' work:**
```bash
# See what agent-1 is working on
cat .agenttrees/tasks/agent-1/*.md

# Read agent-2's notes on the database
cat .agenttrees/notes/agent-2/database-schema.md
```

**Asking for help (async):**
```bash
# Create a question for agent-2
cat > .agenttrees/notes/agent-${AGENT_NUM}/question-for-agent-2.md <<EOF
# Question: Database Migration Issue

@agent-2, I noticed you worked on the database schema.

I'm seeing this error when running migrations:
\`\`\`
Error: Column 'user_id' already exists
\`\`\`

Did you encounter this? How did you fix it?

-- Agent-${AGENT_NUM}
EOF

git -C .agenttrees add .
git -C .agenttrees commit -m "agent-${AGENT_NUM}: Ask agent-2 about migration issue"
git -C .agenttrees push
```

### 5. You Create a PR

When done:
```bash
# Commit your changes
git add .
git commit -m "Fix authentication bug (Issue #42)"

# Push to your branch
git push -u origin agent-${AGENT_NUM}/fix-auth-bug

# Create PR (if gh CLI available)
gh pr create --title "Fix authentication bug" --body "Resolves #42"
```

## Common Tasks

### Check if Other Agents are Working
```bash
# View all agent status
cd ..  # Go to main repo
agenttree status
```

### Update Your Task Log
```bash
# Update your current task log
TASK_LOG=$(ls -t .agenttrees/tasks/agent-${AGENT_NUM}/*.md | head -1)
cat >> "$TASK_LOG" <<EOF

## Progress Update - $(date)

- ✅ Fixed authentication header issue
- ✅ Added tests for token refresh
- 🔄 Working on session timeout handling
EOF

git -C .agenttrees add .
git -C .agenttrees commit -m "agent-${AGENT_NUM}: Update task progress"
git -C .agenttrees push
```

### Find Past Solutions

Check if similar work has been done:
```bash
# Search all specs
grep -r "authentication" .agenttrees/specs/

# Search all notes
grep -r "JWT" .agenttrees/notes/

# Search your own notes
grep -r "token" .agenttrees/notes/agent-${AGENT_NUM}/
```

## Environment Setup

Your worktree was set up by `.agenttrees/scripts/worktree-setup.sh`.

If you encounter issues (missing dependencies, wrong config, etc.):
1. **Fix the setup script** - Other agents will benefit!
2. Test your changes
3. Commit: `git add .agenttrees/scripts/worktree-setup.sh && git commit -m "Fix setup script for <issue>"`

## Best Practices

### ✅ DO

- **Document your findings** in .agenttrees/notes/
- **Update your task log** regularly
- **Fix the setup script** if you find issues
- **Search past work** before starting from scratch
- **Commit often** with clear messages
- **Test your changes** before creating PR
- **Read TASK.md carefully** before starting

### ❌ DON'T

- **Don't interfere** with other agents' worktrees
- **Don't push to main** directly (always use branches)
- **Don't skip tests** to save time
- **Don't ignore errors** in the setup script
- **Don't forget** to document non-obvious solutions

## Troubleshooting

### "My setup failed"
→ Check `.agenttrees/scripts/worktree-setup.sh` and fix it for everyone

### "I can't find my task"
→ Check `TASK.md` in your worktree root, or `.agenttrees/tasks/agent-${AGENT_NUM}/`

### "Where are the other agents' notes?"
→ `.agenttrees/notes/agent-1/`, `.agenttrees/notes/agent-2/`, etc.

### "How do I know what other agents are doing?"
→ Run `cd .. && agenttree status` or check `.agenttrees/tasks/`

### "My port is conflicting"
→ Check `echo $PORT` - each agent has a unique port (you have ${PORT})

## Getting Help

- **Read this guide** first
- **Check .agenttrees/notes/** for past solutions
- **Ask other agents** by creating a note in `.agenttrees/notes/agent-${AGENT_NUM}/`
- **Fix documentation** if you find gaps (including this file!)

## Advanced: ML Learning System (Phase 6)

🚧 Coming soon: AgentTree will learn from merged PRs and suggest solutions.

When implemented, you'll see:
- **Similar past solutions** appended to TASK.md
- **Pattern recommendations** based on successful PRs
- **Cross-project knowledge** (if enabled)

---

**Remember:** You're part of a team. Document your work, help others, and improve the system as you go!

Good luck, Agent-${AGENT_NUM}! 🚀
"""

    with open(agent_guide, "w") as f:
        f.write(agent_guide_template)

    console.print(f"[green]✓ Created {agent_guide}[/green]")
    console.print(f"[dim]  → This guide will be copied to each agent's worktree[/dim]")

    # Initialize agents repository
    console.print("\n[cyan]Initializing agents repository...[/cyan]")
    try:
        ensure_gh_cli()
        agents_repo = AgentsRepository(repo_path)
        agents_repo.ensure_repo()
        console.print("[green]✓ .agenttrees/ repository created[/green]")
    except RuntimeError as e:
        console.print(f"[yellow]Warning: Could not create agents repository:[/yellow]")
        console.print(f"  {e}")
        console.print("\n[yellow]You can create it later by running 'agenttree init' again[/yellow]")

    console.print("\n[bold cyan]Next steps:[/bold cyan]")
    console.print("\n[bold]1. Set up agent-1 and let it configure the environment:[/bold]")
    console.print("   agenttree setup 1")
    console.print("   agenttree dispatch 1 --task 'Test the worktree setup. Run the app, fix any errors in .agenttrees/scripts/worktree-setup.sh, and commit your fixes.'")
    console.print("")
    console.print("[bold]2. Once agent-1 has the setup working, set up the rest:[/bold]")
    console.print("   agenttree setup 2 3  # They'll use agent-1's fixes!")
    console.print("")
    console.print("[bold]3. Start dispatching real work:[/bold]")
    console.print("   agenttree dispatch 2 42  # GitHub issue")
    console.print("   agenttree web            # Or use the dashboard")
    console.print("")
    console.print("[dim]💡 Tip: Agent-1 becomes your sysadmin - it fixes the setup script for everyone![/dim]")


@main.command()
@click.argument("agent_numbers", nargs=-1, type=int, required=True)
def setup(agent_numbers: tuple) -> None:
    """Set up worktrees for agents."""
    repo_path = Path.cwd()
    config = load_config(repo_path)

    manager = WorktreeManager(repo_path, config)

    # Check if custom setup script exists
    setup_script = repo_path / ".agenttrees" / "scripts" / "worktree-setup.sh"
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
@click.argument("agent_num", type=int)
@click.argument("issue_number", type=int, required=False)
@click.option("--task", help="Ad-hoc task description")
@click.option("--tool", help="AI tool to use (default: from config)")
@click.option("--force", is_flag=True, help="Force dispatch even if agent is busy")
def dispatch(
    agent_num: int,
    issue_number: Optional[int],
    task: Optional[str],
    tool: Optional[str],
    force: bool,
) -> None:
    """Dispatch a task to an agent (runs in container)."""
    repo_path = Path.cwd()
    config = load_config(repo_path)

    if not issue_number and not task:
        console.print("[red]Error: Provide either issue number or --task[/red]")
        sys.exit(1)

    # Get worktree path
    worktree_path = config.get_worktree_path(agent_num)

    if not worktree_path.exists():
        console.print(
            f"[red]Error: Agent {agent_num} not set up. Run: agenttree setup {agent_num}[/red]"
        )
        sys.exit(1)

    # Initialize managers
    wt_manager = WorktreeManager(repo_path, config)
    tmux_manager = TmuxManager(config)
    gh_manager = GitHubManager()
    agents_repo = AgentsRepository(repo_path)

    # Ensure agents repo exists
    agents_repo.ensure_repo()

    # Dispatch worktree (reset to main)
    try:
        wt_manager.dispatch(agent_num, force=force)
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    # Create TASK.md
    task_file = worktree_path / "TASK.md"

    if issue_number:
        try:
            issue = get_github_issue(issue_number)
            gh_manager.create_task_file(issue, task_file)
            gh_manager.assign_issue_to_agent(issue_number, agent_num)

            # Create spec and task log in .agenttrees/ repo
            agents_repo.create_spec_file(
                issue_number, issue.title, issue.body, issue.url
            )
            task_log_file = agents_repo.create_task_file(
                agent_num, issue_number, issue.title, issue.body, issue.url
            )

            # Pre-create context summary for task re-engagement
            from datetime import datetime as dt
            from agenttree.agents_repo import slugify
            date = dt.now().strftime("%Y-%m-%d")
            slug = slugify(issue.title)
            task_id = f"agent-{agent_num}-{date}-{slug}"

            agents_repo.create_context_summary(
                agent_num, issue_number, issue.title, task_id
            )

            console.print(f"[green]✓ Created task for issue #{issue_number}[/green]")
            console.print(f"[green]✓ Created spec, task log, and context summary in .agenttrees/ repo[/green]")
        except Exception as e:
            console.print(f"[red]Error fetching issue: {e}[/red]")
            sys.exit(1)
    else:
        gh_manager.create_adhoc_task_file(task or "", task_file)
        console.print("[green]✓ Created ad-hoc task[/green]")

    # Start agent in tmux (always in container)
    tool_name = tool or config.default_tool
    runtime = get_container_runtime()

    if not runtime.is_available():
        console.print(f"[red]Error: No container runtime available[/red]")
        console.print(f"Recommendation: {runtime.get_recommended_action()}")
        sys.exit(1)

    console.print(f"[dim]Container runtime: {runtime.get_runtime_name()}[/dim]")
    tmux_manager.start_agent_in_container(agent_num, worktree_path, tool_name, runtime)
    console.print(f"[green]✓ Started {tool_name} in container[/green]")

    console.print(f"\nCommands:")
    console.print(f"  agenttree attach {agent_num}  # Attach to session")
    console.print(f"  agenttree status             # View all agents")


@main.command()
def status() -> None:
    """Show status of all agents."""
    repo_path = Path.cwd()
    config = load_config(repo_path)

    wt_manager = WorktreeManager(repo_path, config)
    tmux_manager = TmuxManager(config)

    table = Table(title="Agent Status")
    table.add_column("Agent", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Task", style="green")
    table.add_column("Branch", style="yellow")

    # Check agents 1-9 by default
    for agent_num in range(1, 10):
        worktree_path = config.get_worktree_path(agent_num)

        if not worktree_path.exists():
            continue

        status = wt_manager.get_status(agent_num)
        is_running = tmux_manager.is_running(agent_num)

        # Determine status emoji
        if is_running and status.is_busy:
            status_str = "🔴 Busy"
        elif status.is_busy:
            status_str = "🟡 Has task"
        elif is_running:
            status_str = "🟢 Running"
        else:
            status_str = "⚪ Available"

        # Get task description
        task_desc = ""
        if status.has_task:
            task_file = worktree_path / "TASK.md"
            with open(task_file) as f:
                first_line = f.readline().strip()
                task_desc = first_line.replace("# Task: ", "").replace("# Task", "")[:50]

        table.add_row(f"Agent {agent_num}", status_str, task_desc, status.branch)

    console.print(table)


@main.command()
@click.argument("agent_num", type=int)
def attach(agent_num: int) -> None:
    """Attach to an agent's tmux session."""
    config = load_config()
    tmux_manager = TmuxManager(config)

    try:
        console.print(f"Attaching to agent-{agent_num} (Ctrl+B, D to detach)...")
        tmux_manager.attach(agent_num)
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@main.command()
@click.argument("agent_num", type=int)
@click.argument("message")
def send(agent_num: int, message: str) -> None:
    """Send a message to an agent."""
    config = load_config()
    tmux_manager = TmuxManager(config)

    if not tmux_manager.is_running(agent_num):
        console.print(f"[red]Error: Agent {agent_num} is not running[/red]")
        sys.exit(1)

    tmux_manager.send_message(agent_num, message)
    console.print(f"[green]✓ Sent message to agent-{agent_num}[/green]")


@main.command()
@click.argument("agent_num", type=int)
def kill(agent_num: int) -> None:
    """Kill an agent's tmux session."""
    config = load_config()
    tmux_manager = TmuxManager(config)

    tmux_manager.stop_agent(agent_num)
    console.print(f"[green]✓ Killed agent-{agent_num}[/green]")


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

    console.print(f"\n[dim]View task: cat .agenttrees/tasks/agent-{agent_num}/<filename>[/dim]")


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
    - Task dispatch via web UI
    - Command execution for agents
    """
    from agenttree.web.app import run_server

    console.print(f"[cyan]Starting AgentTree dashboard at http://{host}:{port}[/cyan]")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    config_path = Path(config) if config else None
    run_server(host=host, port=port, config_path=config_path)


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
    table.add_column("IP Address", style="green")

    for host in hosts:
        table.add_row(host.get("name", "unknown"), host.get("ip", "unknown"))

    console.print(table)


@remote.command("dispatch")
@click.argument("hostname")
@click.argument("agent_num", type=int)
@click.option("--user", default="agent", help="SSH user")
@click.option("--agents-repo", default="~/agents", help="Path to agents repo on remote")
def remote_dispatch(hostname: str, agent_num: int, user: str, agents_repo: str) -> None:
    """Dispatch a task to a remote agent.

    This will:
    1. SSH into the remote host
    2. Pull latest from .agenttrees/ repo
    3. Notify the agent's tmux session

    Example:
        agenttree remote dispatch my-home-pc 1
    """
    from agenttree.remote import RemoteHost, dispatch_task_to_remote_agent

    host = RemoteHost(name=hostname, host=hostname, user=user, is_tailscale=True)

    console.print(f"[cyan]Dispatching task to {hostname} agent-{agent_num}...[/cyan]")

    success = dispatch_task_to_remote_agent(
        host,
        agent_num,
        project_name="agenttree",  # Could be made configurable
        agents_repo_path=agents_repo
    )

    if success:
        console.print(f"[green]✓ Task dispatched to {hostname}[/green]")
    else:
        console.print(f"[red]✗ Failed to dispatch task[/red]")
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

    Issues are stored in .agenttrees/issues/ and track work through
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
def issue_create(title: str, priority: str, label: tuple) -> None:
    """Create a new issue.

    Creates an issue directory in .agenttrees/issues/ with:
    - issue.yaml (metadata)
    - problem.md (from template)

    Example:
        agenttree issue create "Fix login validation"
        agenttree issue create "Add dark mode" -p high -l ui -l feature
    """
    try:
        issue = create_issue_func(
            title=title,
            priority=Priority(priority),
            labels=list(label) if label else None,
        )
        console.print(f"[green]✓ Created issue {issue.id}: {issue.title}[/green]")
        console.print(f"[dim]  Directory: .agenttrees/issues/{issue.id}-{issue.slug}/[/dim]")
        console.print(f"[dim]  Edit problem.md to define the problem[/dim]")
    except Exception as e:
        console.print(f"[red]Error creating issue: {e}[/red]")
        sys.exit(1)


@issue.command("list")
@click.option(
    "--stage", "-s",
    type=click.Choice([s.value for s in Stage]),
    help="Filter by stage"
)
@click.option(
    "--priority", "-p",
    type=click.Choice([p.value for p in Priority]),
    help="Filter by priority"
)
@click.option(
    "--agent", "-a",
    type=int,
    help="Filter by assigned agent"
)
@click.option(
    "--json", "as_json",
    is_flag=True,
    help="Output as JSON"
)
def issue_list(stage: Optional[str], priority: Optional[str], agent: Optional[int], as_json: bool) -> None:
    """List issues.

    Examples:
        agenttree issue list
        agenttree issue list --stage backlog
        agenttree issue list -s implement -p high
        agenttree issue list --json
    """
    stage_filter = Stage(stage) if stage else None
    priority_filter = Priority(priority) if priority else None

    issues = list_issues_func(
        stage=stage_filter,
        priority=priority_filter,
        assigned_agent=agent,
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
    table.add_column("Agent", style="green")

    for issue in issues:
        agent_str = f"Agent {issue.assigned_agent}" if issue.assigned_agent else "-"
        stage_str = issue.stage.value
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
            agent_str,
        )

    console.print(table)


@issue.command("show")
@click.argument("issue_id")
def issue_show(issue_id: str) -> None:
    """Show issue details.

    Examples:
        agenttree issue show 001
        agenttree issue show 1
        agenttree issue show 001-fix-login
    """
    issue = get_issue_func(issue_id)

    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    issue_dir = get_issue_dir(issue_id)

    console.print(f"\n[bold cyan]Issue {issue.id}: {issue.title}[/bold cyan]\n")

    # Basic info
    console.print(f"[bold]Stage:[/bold] {issue.stage.value}", end="")
    if issue.substage:
        console.print(f".{issue.substage}")
    else:
        console.print()

    console.print(f"[bold]Priority:[/bold] {issue.priority.value}")

    if issue.assigned_agent:
        console.print(f"[bold]Assigned:[/bold] Agent {issue.assigned_agent}")

    if issue.labels:
        console.print(f"[bold]Labels:[/bold] {', '.join(issue.labels)}")

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
            stage_str = entry.stage
            if entry.substage:
                stage_str += f".{entry.substage}"
            agent_str = f" (agent {entry.agent})" if entry.agent else ""
            console.print(f"  • {entry.timestamp[:10]} → {stage_str}{agent_str}")

    console.print(f"\n[dim]Directory: {issue_dir}[/dim]")


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
        console.print("[yellow]No issue specified. Use --issue flag or run from agent worktree.[/yellow]")
        console.print("[dim]Showing all active issues:[/dim]\n")

        # Show all non-backlog, non-accepted issues
        active_issues = [
            i for i in list_issues_func()
            if i.stage not in (Stage.BACKLOG, Stage.ACCEPTED, Stage.NOT_DOING)
        ]

        if not active_issues:
            console.print("[dim]No active issues[/dim]")
            return

        table = Table(title="Active Issues")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Stage", style="magenta")
        table.add_column("Agent", style="green")

        for issue in active_issues:
            stage_str = issue.stage.value
            if issue.substage:
                stage_str += f".{issue.substage}"
            agent_str = f"Agent {issue.assigned_agent}" if issue.assigned_agent else "-"
            table.add_row(issue.id, issue.title[:40], stage_str, agent_str)

        console.print(table)
        return

    issue = get_issue_func(issue_id)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    console.print(f"\n[bold cyan]Issue {issue.id}: {issue.title}[/bold cyan]")
    console.print(f"[bold]Stage:[/bold] {issue.stage.value}", end="")
    if issue.substage:
        console.print(f".{issue.substage}")
    else:
        console.print()

    if issue.assigned_agent:
        console.print(f"[bold]Agent:[/bold] {issue.assigned_agent}")

    if issue.stage in HUMAN_REVIEW_STAGES:
        console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
    elif issue.stage == Stage.ACCEPTED:
        console.print(f"\n[green]✓ Issue completed[/green]")


@main.command("begin")
@click.argument("stage", type=click.Choice([s.value for s in Stage]))
@click.option("--issue", "-i", "issue_id", required=True, help="Issue ID")
def stage_begin(stage: str, issue_id: str) -> None:
    """Begin working on a stage. Returns stage instructions.

    Examples:
        agenttree begin problem --issue 001
        agenttree begin research --issue 002
    """
    issue = get_issue_func(issue_id)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    target_stage = Stage(stage)

    # Get substages for this stage
    from agenttree.issues import STAGE_SUBSTAGES
    substages = STAGE_SUBSTAGES.get(target_stage, [])
    substage = substages[0] if substages else None

    # Update issue to this stage
    updated = update_issue_stage(issue_id, target_stage, substage)
    if not updated:
        console.print(f"[red]Failed to update issue[/red]")
        sys.exit(1)

    stage_str = target_stage.value
    if substage:
        stage_str += f".{substage}"
    console.print(f"[green]✓ Started {stage_str}[/green]")

    # Load and display skill
    skill = load_skill(target_stage, substage)
    if skill:
        console.print(f"\n{'='*60}")
        console.print(f"[bold cyan]Stage Instructions: {target_stage.value.upper()}[/bold cyan]")
        console.print(f"{'='*60}\n")
        console.print(skill)
    else:
        console.print(f"\n[dim]No skill file found for {target_stage.value}[/dim]")

    # Show relevant files
    issue_dir = get_issue_dir(issue_id)
    if issue_dir:
        console.print(f"\n[bold]Issue files:[/bold]")
        for file in sorted(issue_dir.iterdir()):
            if file.is_file():
                console.print(f"  • {file.name}")


@main.command("next")
@click.option("--issue", "-i", "issue_id", required=True, help="Issue ID")
def stage_next(issue_id: str) -> None:
    """Move to the next substage or stage.

    Examples:
        agenttree next --issue 001
    """
    issue = get_issue_func(issue_id)
    if not issue:
        console.print(f"[red]Issue {issue_id} not found[/red]")
        sys.exit(1)

    if issue.stage == Stage.ACCEPTED:
        console.print(f"[yellow]Issue is already accepted[/yellow]")
        return

    if issue.stage == Stage.NOT_DOING:
        console.print(f"[yellow]Issue is marked as not doing[/yellow]")
        return

    # Calculate next stage
    next_stage, next_substage, is_human_review = get_next_stage(
        issue.stage, issue.substage
    )

    # Check if we're already at the next stage (no change)
    if next_stage == issue.stage and next_substage == issue.substage:
        console.print(f"[yellow]Already at final stage[/yellow]")
        return

    # Update issue
    updated = update_issue_stage(issue_id, next_stage, next_substage)
    if not updated:
        console.print(f"[red]Failed to update issue[/red]")
        sys.exit(1)

    stage_str = next_stage.value
    if next_substage:
        stage_str += f".{next_substage}"
    console.print(f"[green]✓ Moved to {stage_str}[/green]")

    if is_human_review:
        console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
        console.print(f"[dim]Your work has been submitted for review.[/dim]")
        console.print(f"[dim]You will receive instructions when the review is complete.[/dim]")
        return

    # Load and display skill for next stage
    skill = load_skill(next_stage, next_substage)
    if skill:
        console.print(f"\n{'='*60}")
        header = f"Stage Instructions: {next_stage.value.upper()}"
        if next_substage:
            header += f" ({next_substage})"
        console.print(f"[bold cyan]{header}[/bold cyan]")
        console.print(f"{'='*60}\n")
        console.print(skill)


# =============================================================================
# Agent Context Commands
# =============================================================================

@main.command("context-init")
@click.option("--agent", "-a", "agent_num", type=int, help="Agent number (reads from .env if not provided)")
@click.option("--port", "-p", "port", type=int, help="Agent port (derived from agent number if not provided)")
def context_init(agent_num: Optional[int], port: Optional[int]) -> None:
    """Initialize agent context in current worktree.

    This command:
    1. Clones the .agenttrees repo into the current directory
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

    # Check if .agenttrees already exists
    agenttrees_path = cwd / ".agenttrees"
    if agenttrees_path.exists() and (agenttrees_path / ".git").exists():
        console.print(f"[green]✓ .agenttrees already exists[/green]")
    else:
        # Try to find the remote URL from the main project
        # Go up directories to find the main .agenttrees repo
        main_agenttrees = None
        parent = cwd.parent
        for _ in range(5):  # Check up to 5 levels up
            candidate = parent / ".agenttrees"
            if candidate.exists() and (candidate / ".git").exists():
                main_agenttrees = candidate
                break
            parent = parent.parent

        if main_agenttrees is None:
            console.print("[red]Error: Could not find main .agenttrees repo[/red]")
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
            console.print("[red]Error: Could not get remote URL from main .agenttrees[/red]")
            sys.exit(1)

        # Clone the repo
        console.print(f"[cyan]Cloning .agenttrees from {remote_url}...[/cyan]")
        try:
            subprocess.run(
                ["git", "clone", remote_url, ".agenttrees"],
                cwd=cwd,
                check=True,
            )
            console.print(f"[green]✓ Cloned .agenttrees[/green]")
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
    console.print(f"  .agenttrees/ - Issues, skills, templates")
    console.print(f"  .env - AGENT_NUM={agent_num}, PORT={port}")
    console.print(f"\n[dim]Read CLAUDE.md for workflow instructions[/dim]")


if __name__ == "__main__":
    main()
