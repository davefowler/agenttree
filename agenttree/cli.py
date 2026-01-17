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
    get_next_stage,
    update_issue_stage,
    update_issue_metadata,
    load_skill,
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
    execute_pre_hooks,
    execute_post_hooks,
    ValidationError,
    is_running_in_container,
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

    # Create _agenttree/scripts directory
    scripts_dir = repo_path / "_agenttree" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    # Create worktree-setup.sh template
    setup_script = scripts_dir / "worktree-setup.sh"
    setup_template = r"""#!/bin/bash
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
if [ -f "../_agenttree/templates/AGENT_GUIDE.md" ]; then
    sed "s/\${AGENT_NUM}/$AGENT_NUM/g; s/\${PORT}/$AGENT_PORT/g" ../_agenttree/templates/AGENT_GUIDE.md > AGENT_GUIDE.md
    echo "✓ Created personalized AGENT_GUIDE.md"
fi

echo ""
echo "✅ Agent-$AGENT_NUM setup complete!"
echo ""
echo "📝 Your identity:"
echo "   AGENT_NUM: $AGENT_NUM"
echo "   PORT: $AGENT_PORT"
echo "   Your notes: _agenttree/tasks/agent-$AGENT_NUM/"
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
    templates_dir = repo_path / "_agenttree" / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)
    agent_guide = templates_dir / "AGENT_GUIDE.md"
    agent_guide_template = r"""# AgentTree Agent Guide

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
├── _agenttree/                ← Shared repo (issues, skills, scripts)
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

When started, you'll find:
- **TASK.md** in your worktree root
- **_agenttree/specs/issue-<num>.md** with the full specification
- **_agenttree/tasks/agent-${AGENT_NUM}/<timestamp>-issue-<num>.md** your task log

### 2. You Work on It

- Read TASK.md first
- Check _agenttree/specs/ for detailed requirements
- Look at _agenttree/notes/ to see what other agents have learned
- Write code, run tests, fix bugs
- Commit your changes regularly

### 3. You Document Your Work

Create notes for other agents:

```bash
# Create a note about your findings
cat > _agenttree/notes/agent-${AGENT_NUM}/api-authentication.md <<EOF
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

git -C _agenttree add .
git -C _agenttree commit -m "agent-${AGENT_NUM}: Document API auth pattern"
git -C _agenttree push
```

### 4. You Collaborate

**Reading other agents' work:**
```bash
# See what agent-1 is working on
cat _agenttree/tasks/agent-1/*.md

# Read agent-2's notes on the database
cat _agenttree/notes/agent-2/database-schema.md
```

**Asking for help (async):**
```bash
# Create a question for agent-2
cat > _agenttree/notes/agent-${AGENT_NUM}/question-for-agent-2.md <<EOF
# Question: Database Migration Issue

@agent-2, I noticed you worked on the database schema.

I'm seeing this error when running migrations:
\`\`\`
Error: Column 'user_id' already exists
\`\`\`

Did you encounter this? How did you fix it?

-- Agent-${AGENT_NUM}
EOF

git -C _agenttree add .
git -C _agenttree commit -m "agent-${AGENT_NUM}: Ask agent-2 about migration issue"
git -C _agenttree push
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
TASK_LOG=$(ls -t _agenttree/tasks/agent-${AGENT_NUM}/*.md | head -1)
cat >> "$TASK_LOG" <<EOF

## Progress Update - $(date)

- ✅ Fixed authentication header issue
- ✅ Added tests for token refresh
- 🔄 Working on session timeout handling
EOF

git -C _agenttree add .
git -C _agenttree commit -m "agent-${AGENT_NUM}: Update task progress"
git -C _agenttree push
```

### Find Past Solutions

Check if similar work has been done:
```bash
# Search all specs
grep -r "authentication" _agenttree/specs/

# Search all notes
grep -r "JWT" _agenttree/notes/

# Search your own notes
grep -r "token" _agenttree/notes/agent-${AGENT_NUM}/
```

## Environment Setup

Your worktree was set up by `_agenttree/scripts/worktree-setup.sh`.

If you encounter issues (missing dependencies, wrong config, etc.):
1. **Fix the setup script** - Other agents will benefit!
2. Test your changes
3. Commit: `git add _agenttree/scripts/worktree-setup.sh && git commit -m "Fix setup script for <issue>"`

## Best Practices

### ✅ DO

- **Document your findings** in _agenttree/notes/
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
→ Check `_agenttree/scripts/worktree-setup.sh` and fix it for everyone

### "I can't find my task"
→ Check `TASK.md` in your worktree root, or `_agenttree/tasks/agent-${AGENT_NUM}/`

### "Where are the other agents' notes?"
→ `_agenttree/notes/agent-1/`, `_agenttree/notes/agent-2/`, etc.

### "How do I know what other agents are doing?"
→ Run `cd .. && agenttree status` or check `_agenttree/tasks/`

### "My port is conflicting"
→ Check `echo $PORT` - each agent has a unique port (you have ${PORT})

## Getting Help

- **Read this guide** first
- **Check _agenttree/notes/** for past solutions
- **Ask other agents** by creating a note in `_agenttree/notes/agent-${AGENT_NUM}/`
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
    # Note: gh CLI and auth were already validated in check_all_dependencies()
    console.print("\n[cyan]Initializing agents repository...[/cyan]")
    try:
        agents_repo = AgentsRepository(repo_path)
        agents_repo.ensure_repo()
        console.print("[green]✓ _agenttree/ repository created[/green]")
    except RuntimeError as e:
        console.print(f"[yellow]Warning: Could not create agents repository:[/yellow]")
        console.print(f"  {e}")
        console.print("\n[yellow]You can create it later by running 'agenttree init' again[/yellow]")

    console.print("\n[bold cyan]Next steps:[/bold cyan]")
    console.print("\n[bold]1. Set up agent-1 and let it configure the environment:[/bold]")
    console.print("   agenttree setup 1")
    console.print("   agenttree start 1 --task 'Test the worktree setup. Run the app, fix any errors in _agenttree/scripts/worktree-setup.sh, and commit your fixes.'")
    console.print("")
    console.print("[bold]2. Once agent-1 has the setup working, set up the rest:[/bold]")
    console.print("   agenttree setup 2 3  # They'll use agent-1's fixes!")
    console.print("")
    console.print("[bold]3. Start assigning real work:[/bold]")
    console.print("   agenttree start 2 --task 'Fix the login bug'")
    console.print("   agenttree tui            # Or use the terminal dashboard")
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


@main.command(name="start")
@click.argument("issue_id", type=str)
@click.option("--tool", help="AI tool to use (default: from config)")
@click.option("--force", is_flag=True, help="Force start even if agent already exists")
@click.option("--skip-preflight", is_flag=True, help="Skip preflight environment checks")
def start_agent(
    issue_id: str,
    tool: Optional[str],
    force: bool,
    skip_preflight: bool,
) -> None:
    """Start an agent for an issue (creates container + worktree).

    ISSUE_ID is the issue number (e.g., "23" or "023").

    This creates a dedicated agent for the issue with:
    - A new worktree (issue-023-slug/)
    - A new container (agenttree-issue-023)
    - A tmux session for interaction

    The agent is automatically cleaned up when the issue is accepted.
    """
    from agenttree.state import (
        get_active_agent,
        get_port_for_issue,
        create_agent_for_issue,
        get_issue_names,
    )
    from agenttree.worktree import create_worktree, update_worktree_with_main
    from agenttree.issues import assign_agent

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

    # Check if issue already has an active agent
    existing_agent = get_active_agent(issue.id)
    if existing_agent and not force:
        console.print(f"[yellow]Issue #{issue.id} already has an active agent[/yellow]")
        console.print(f"  Container: {existing_agent.container}")
        console.print(f"  Port: {existing_agent.port}")
        console.print(f"\nUse --force to replace it, or attach with:")
        console.print(f"  agenttree attach {issue.id}")
        sys.exit(1)

    # Initialize managers
    tmux_manager = TmuxManager(config)
    agents_repo = AgentsRepository(repo_path)

    # Ensure agents repo exists
    agents_repo.ensure_repo()

    # Get names for this issue
    names = get_issue_names(issue.id, issue.slug, config.project)

    # Create worktree for issue
    worktree_path = config.get_issue_worktree_path(issue.id, issue.slug)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    if worktree_path.exists():
        # Worktree exists - this is a restart scenario
        # Update with latest main to get newest CLI code while preserving agent's work
        console.print(f"[cyan]Updating existing worktree with latest main...[/cyan]")
        update_success = update_worktree_with_main(worktree_path)
        if update_success:
            console.print(f"[green]✓ Worktree updated successfully[/green]")
        else:
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
            console.print(f"[dim]Creating worktree from existing branch: {names['branch']}[/dim]")
            create_worktree(repo_path, worktree_path, names["branch"])
            console.print(f"[cyan]Updating with latest main...[/cyan]")
            update_success = update_worktree_with_main(worktree_path)
            if update_success:
                console.print(f"[green]✓ Worktree updated successfully[/green]")
            else:
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
    )

    # Mark issue as having an assigned agent (for web UI status light)
    assign_agent(issue.id, int(issue.id))

    # Save branch and worktree info to issue metadata
    update_issue_metadata(issue.id, branch=names["branch"], worktree_dir=str(worktree_path))

    console.print(f"[green]✓ Starting agent for issue #{issue.id}: {issue.title}[/green]")

    # Create session for restart detection
    create_session(issue.id)

    # Start agent in tmux (always in container)
    tool_name = tool or config.default_tool
    runtime = get_container_runtime()

    if not runtime.is_available():
        console.print(f"[red]Error: No container runtime available[/red]")
        console.print(f"Recommendation: {runtime.get_recommended_action()}")
        sys.exit(1)

    console.print(f"[dim]Container runtime: {runtime.get_runtime_name()}[/dim]")
    tmux_manager.start_issue_agent_in_container(
        issue_id=issue.id,
        session_name=agent.tmux_session,
        worktree_path=worktree_path,
        tool_name=tool_name,
        container_runtime=runtime,
    )
    console.print(f"[green]✓ Started {tool_name} in container[/green]")

    console.print(f"\n[bold]Agent ready for issue #{issue.id}[/bold]")
    console.print(f"  Container: {agent.container}")
    console.print(f"  Port: {agent.port}")
    console.print(f"\n[dim]Commands:[/dim]")
    console.print(f"  agenttree attach {issue.id}")
    console.print(f"  agenttree send {issue.id} 'message'")
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
    table.add_column("Title", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Port", style="green")
    table.add_column("Branch", style="yellow")

    for agent in agents:
        # Check if tmux session is running
        is_running = tmux_manager.is_issue_running(agent.tmux_session)

        # Get issue info
        issue = get_issue_func(agent.issue_id)
        issue_title = issue.title[:35] if issue else "Unknown"

        # Determine status
        if is_running:
            status_str = "🟢 Running"
        else:
            status_str = "⚪ Stopped"

        table.add_row(
            agent.issue_id,
            issue_title,
            status_str,
            str(agent.port),
            agent.branch[:25],
        )

    console.print(table)
    console.print(f"\n[dim]Commands (use ID from table above):[/dim]")
    console.print(f"  agenttree attach <id>")
    console.print(f"  agenttree send <id> 'message'")
    console.print(f"  agenttree kill <id>")


@main.command()
@click.argument("issue_id", type=str)
def attach(issue_id: str) -> None:
    """Attach to an issue's agent tmux session.

    ISSUE_ID is the issue number (e.g., "23" or "023").
    """
    from agenttree.state import get_active_agent

    config = load_config()
    tmux_manager = TmuxManager(config)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Get active agent for this issue
    agent = get_active_agent(issue_id_normalized)
    if not agent:
        # Try with padded ID
        issue = get_issue_func(issue_id_normalized)
        if issue:
            agent = get_active_agent(issue.id)

    if not agent:
        console.print(f"[red]Error: No active agent for issue #{issue_id}[/red]")
        console.print(f"[yellow]Start one with: agenttree start {issue_id}[/yellow]")
        sys.exit(1)

    try:
        console.print(f"Attaching to issue #{agent.issue_id} (Ctrl+B, D to detach)...")
        tmux_manager.attach_to_issue(agent.tmux_session)
    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


@main.command()
@click.argument("issue_id", type=str)
@click.argument("message")
def send(issue_id: str, message: str) -> None:
    """Send a message to an issue's agent.

    ISSUE_ID is the issue number (e.g., "23" or "023").
    """
    from agenttree.state import get_active_agent

    config = load_config()
    tmux_manager = TmuxManager(config)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Get active agent for this issue
    agent = get_active_agent(issue_id_normalized)
    if not agent:
        issue = get_issue_func(issue_id_normalized)
        if issue:
            agent = get_active_agent(issue.id)

    if not agent:
        console.print(f"[red]Error: No active agent for issue #{issue_id}[/red]")
        console.print(f"[yellow]Start one with: agenttree start {issue_id}[/yellow]")
        sys.exit(1)

    if not tmux_manager.is_issue_running(agent.tmux_session):
        console.print(f"[red]Error: Agent for issue #{issue_id} is not running[/red]")
        sys.exit(1)

    tmux_manager.send_message_to_issue(agent.tmux_session, message)
    console.print(f"[green]✓ Sent message to issue #{agent.issue_id}[/green]")


@main.command()
@click.argument("issue_id", type=str)
def kill(issue_id: str) -> None:
    """Kill an issue's agent tmux session.

    ISSUE_ID is the issue number (e.g., "23" or "023").
    """
    from agenttree.state import get_active_agent, unregister_agent

    config = load_config()
    tmux_manager = TmuxManager(config)

    # Normalize issue ID
    issue_id_normalized = issue_id.lstrip("0") or "0"

    # Get active agent for this issue
    agent = get_active_agent(issue_id_normalized)
    if not agent:
        issue = get_issue_func(issue_id_normalized)
        if issue:
            agent = get_active_agent(issue.id)

    if not agent:
        console.print(f"[red]Error: No active agent for issue #{issue_id}[/red]")
        sys.exit(1)

    tmux_manager.stop_issue_agent(agent.tmux_session)
    unregister_agent(agent.issue_id)

    # Clear assigned_agent in issue metadata to prevent ghost status
    from agenttree.issues import update_issue_metadata
    update_issue_metadata(agent.issue_id, clear_assigned_agent=True)

    console.print(f"[green]✓ Killed agent for issue #{agent.issue_id}[/green]")


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
    "--problem",
    help="Problem statement (fills problem.md)"
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
@click.pass_context
def issue_create(
    ctx: click.Context,
    title: str,
    priority: str,
    label: tuple,
    stage: str,
    problem: Optional[str],
    context: Optional[str],
    solutions: Optional[str],
    depends_on: tuple,
) -> None:
    """Create a new issue.

    Creates an issue directory in _agenttree/issues/ with:
    - issue.yaml (metadata)
    - problem.md (from template or provided content)

    After creating, fill in problem.md then run 'agenttree start <id>' to
    start an agent.

    Issues with unmet dependencies are placed in backlog and auto-started when
    all dependencies are completed.

    Example:
        agenttree issue create "Fix login validation"
        agenttree issue create "Add dark mode" -p high -l ui -l feature
        agenttree issue create "Quick fix" --stage implement
        agenttree issue create "Bug" --problem "The login fails" --context "On Chrome only"
        agenttree issue create "Feature B" --depends-on 053 --depends-on 060
    """

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
            problem=problem,
            context=context,
            solutions=solutions,
            dependencies=dependencies,
        )
        console.print(f"[green]✓ Created issue {issue.id}: {issue.title}[/green]")
        console.print(f"[dim]  _agenttree/issues/{issue.id}-{issue.slug}/[/dim]")
        console.print(f"[dim]  Stage: {issue.stage}[/dim]")
        if issue.dependencies:
            console.print(f"[dim]  Dependencies: {', '.join(issue.dependencies)}[/dim]")

        # Show next steps
        if has_unmet_deps:
            console.print(f"\n[yellow]Issue blocked by dependencies - will auto-start when deps complete[/yellow]")
        else:
            console.print(f"\n[bold]Next steps:[/bold]")
            console.print(f"  1. Fill in problem.md: [cyan]_agenttree/issues/{issue.id}-{issue.slug}/problem.md[/cyan]")
            console.print(f"  2. Start agent: [cyan]agenttree start {issue.id}[/cyan]")

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
    stage_filter = stage if stage else None
    priority_filter = Priority(priority) if priority else None
    agent_filter = str(agent) if agent is not None else None

    issues = list_issues_func(
        stage=stage_filter,
        priority=priority_filter,
        assigned_agent=agent_filter,
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
    console.print(f"[bold]Stage:[/bold] {issue.stage}", end="")
    if issue.substage:
        console.print(f".{issue.substage}")
    else:
        console.print()

    console.print(f"[bold]Priority:[/bold] {issue.priority.value}")

    if issue.assigned_agent:
        console.print(f"[bold]Assigned:[/bold] Agent {issue.assigned_agent}")

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

        table = Table(title="Active Issues")
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Stage", style="magenta")
        table.add_column("Agent", style="green")

        for active_issue in active_issues:
            stage_str = active_issue.stage
            if active_issue.substage:
                stage_str += f".{active_issue.substage}"
            agent_str = f"Agent {active_issue.assigned_agent}" if active_issue.assigned_agent else "-"
            table.add_row(active_issue.id, active_issue.title[:40], stage_str, agent_str)

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

    if issue.assigned_agent:
        console.print(f"[bold]Agent:[/bold] {issue.assigned_agent}")

    if issue.stage in HUMAN_REVIEW_STAGES:
        console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
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

    # Block agents from advancing past human review gates
    if issue.stage in HUMAN_REVIEW_STAGES and is_running_in_container():
        console.print(f"\n[yellow]⏳ Waiting for human approval[/yellow]")
        console.print(f"[dim]Stage '{issue.stage}' requires human review.[/dim]")
        console.print(f"[dim]A human will run 'agenttree approve {issue.id}' when ready.[/dim]")
        return

    # Check for restart and re-orient if needed
    session = get_session(issue_id)
    if session is None:
        # No session exists - create one (fresh start or legacy case)
        session = create_session(issue_id)

    if is_restart(issue_id):
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

        # Load and display current stage instructions
        skill = load_skill(issue.stage, issue.substage, issue=issue)
        if skill:
            console.print(f"\n{'='*60}")
            console.print(f"[bold cyan]Continue working on: {issue.stage.upper()}[/bold cyan]")
            console.print(f"{'='*60}\n")
            console.print(skill)

        console.print(f"\n[dim]When ready to advance, run 'agenttree next' again.[/dim]")

        # Mark as oriented so next call will advance
        mark_session_oriented(issue_id)
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
            issue.stage, issue.substage
        )

    # Check if we're already at the next stage (no change)
    if next_stage == issue.stage and next_substage == issue.substage:
        console.print(f"[yellow]Already at final stage[/yellow]")
        return

    # Execute pre-hooks (can block with ValidationError)
    from_stage = issue.stage
    from_substage = issue.substage
    try:
        execute_pre_hooks(issue, from_stage, from_substage)
    except ValidationError as e:
        console.print(f"[red]Cannot proceed: {e}[/red]")
        sys.exit(1)

    # Update issue stage in database
    updated = update_issue_stage(issue_id, next_stage, next_substage)
    if not updated:
        console.print(f"[red]Failed to update issue[/red]")
        sys.exit(1)

    # Update session to track stage advancement
    update_session_stage(issue_id, next_stage, next_substage)

    # Execute post-hooks (after stage updated)
    execute_post_hooks(updated, next_stage, next_substage)

    stage_str = next_stage
    if next_substage:
        stage_str += f".{next_substage}"
    console.print(f"[green]✓ Moved to {stage_str}[/green]")

    if is_human_review:
        console.print(f"\n[yellow]⏳ Waiting for human review[/yellow]")
        console.print(f"[dim]Your work has been submitted for review.[/dim]")
        console.print(f"[dim]You will receive instructions when the review is complete.[/dim]")
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

    # Check if at human review stage
    if issue.stage not in HUMAN_REVIEW_STAGES:
        console.print(f"[red]Issue is at '{issue.stage}', not a human review stage[/red]")
        console.print(f"[dim]Human review stages: {', '.join(HUMAN_REVIEW_STAGES)}[/dim]")
        sys.exit(1)

    # Calculate next stage
    next_stage, next_substage, _ = get_next_stage(issue.stage, issue.substage)

    # Execute pre-hooks
    from_stage = issue.stage
    from_substage = issue.substage
    try:
        execute_pre_hooks(issue, from_stage, from_substage, skip_pr_approval=skip_approval)
    except ValidationError as e:
        console.print(f"[red]Cannot approve: {e}[/red]")
        sys.exit(1)

    # Update issue stage
    updated = update_issue_stage(issue_id_normalized, next_stage, next_substage)
    if not updated:
        console.print(f"[red]Failed to update issue[/red]")
        sys.exit(1)

    # Update session
    update_session_stage(issue_id_normalized, next_stage, next_substage)

    # Execute post-hooks (after stage updated)
    execute_post_hooks(updated, next_stage, next_substage)

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
    from agenttree.issues import get_agenttree_path

    console.print("[dim]Syncing agents repository...[/dim]")
    agents_path = get_agenttree_path()
    success = sync_agents_repo(agents_path)

    if success:
        console.print("[green]✓ Sync complete[/green]")
    else:
        console.print("[yellow]Sync completed with warnings[/yellow]")


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
        next_stage, next_substage, _ = get_next_stage(issue.stage, issue.substage)
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


if __name__ == "__main__":
    main()
