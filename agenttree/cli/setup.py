"""Setup commands (init, upgrade, setup, preflight, migrate-docs)."""

import shutil
import subprocess
import sys
from pathlib import Path

import click

from agenttree.cli._utils import console, load_config
from agenttree.worktree import WorktreeManager
from agenttree.agents_repo import AgentsRepository
from agenttree.dependencies import check_all_dependencies, print_dependency_report
from agenttree.preflight import run_preflight


# AI notes patterns to detect (case-insensitive)
AI_NOTES_PATTERNS = [
    "*CLAUDE*.md",
    "*AI*.md",
    "*AGENT*.md",
    "*NOTES*.md",
]

# Directories that commonly contain AI-generated notes
AI_NOTES_DIRS = [
    "docs/ai-notes",
    "docs/notes",
    "notes",
]

# Files to exclude from migration (project documentation, not AI notes)
EXCLUDE_FILES = {
    "README.md",
    "readme.md",
    "CHANGELOG.md",
    "changelog.md",
}


def _detect_ai_notes(repo_path: Path) -> list[Path]:
    """Detect AI-generated notes files in the repository.

    Scans for common AI notes patterns:
    - Files: *CLAUDE*.md, *AI*.md, *AGENT*.md, *NOTES*.md (case-insensitive)
    - Directories: docs/ai-notes/, docs/notes/, notes/

    Args:
        repo_path: Path to the repository root

    Returns:
        List of paths to detected AI notes files, sorted alphabetically
    """
    found: set[Path] = set()

    # Scan for pattern-matched files in repo root and common locations
    for pattern in AI_NOTES_PATTERNS:
        # Case-insensitive glob by checking both cases
        for match in repo_path.glob(pattern):
            if match.name not in EXCLUDE_FILES and match.is_file():
                # Skip files already in _agenttree
                if "_agenttree" not in match.parts:
                    found.add(match)
        # Also check lowercase version
        for match in repo_path.glob(pattern.lower()):
            if match.name not in EXCLUDE_FILES and match.is_file():
                if "_agenttree" not in match.parts:
                    found.add(match)

    # Scan AI notes directories
    for dir_name in AI_NOTES_DIRS:
        dir_path = repo_path / dir_name
        if dir_path.exists() and dir_path.is_dir():
            for match in dir_path.rglob("*"):
                if match.is_file() and "_agenttree" not in match.parts:
                    found.add(match)

    return sorted(found)


def _migrate_notes(repo_path: Path, notes: list[Path], agents_path: Path) -> int:
    """Migrate AI notes files to _agenttree/notes/.

    Preserves relative path structure. Uses git mv for tracked files,
    regular move for untracked files.

    Args:
        repo_path: Path to the repository root
        notes: List of note file paths to migrate
        agents_path: Path to _agenttree directory

    Returns:
        Number of files successfully migrated
    """
    notes_dir = agents_path / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    migrated = 0
    for note_path in notes:
        # Calculate relative path from repo root
        rel_path = note_path.relative_to(repo_path)
        dest_path = notes_dir / rel_path

        # Create parent directories
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Check if file is tracked by git
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(note_path)],
            cwd=repo_path,
            capture_output=True,
        )
        is_tracked = result.returncode == 0

        try:
            if is_tracked:
                # Use git mv to preserve history
                subprocess.run(
                    ["git", "mv", str(note_path), str(dest_path)],
                    cwd=repo_path,
                    check=True,
                    capture_output=True,
                )
            else:
                # Regular file move
                shutil.move(str(note_path), str(dest_path))

            migrated += 1
            console.print(f"  [green]✓[/green] {rel_path}")
        except Exception as e:
            console.print(f"  [red]✗[/red] {rel_path}: {e}")

    return migrated


def _create_knowledge_issue(repo_path: Path) -> None:
    """Create a knowledge base population issue.

    This issue guides an agent to analyze the codebase and populate
    the knowledge base with codebase-specific information.

    Args:
        repo_path: Path to the repository root
    """
    from agenttree.issues import create_issue, Priority

    problem = """Analyze this codebase and populate the knowledge base with useful information for future agents.

## Tasks

1. **Read and understand the codebase**
   - Read README.md and any documentation
   - Identify the tech stack (language, framework, tools)
   - Understand the project structure

2. **Extract useful commands**
   - Build commands (e.g., `npm run build`, `uv run pytest`)
   - Test commands
   - Development server commands
   - Any custom scripts

3. **Document patterns and conventions**
   - Code style preferences
   - Common patterns used in the codebase
   - Architecture decisions

4. **Note any gotchas**
   - Known issues or quirks
   - Things that might trip up new developers
   - Environment setup requirements

## Output

Document your findings in `_agenttree/notes/`:
- `commands.md` - Common commands and scripts
- `patterns.md` - Code patterns and conventions
- `gotchas.md` - Known issues and quirks
- `architecture.md` - Project structure and architecture"""

    try:
        issue = create_issue(
            title="Populate knowledge base with codebase-specific information",
            priority=Priority.MEDIUM,
            problem=problem,
            stage="backlog",  # Start in backlog - user can start when ready
        )
        console.print(f"[green]✓ Created knowledge base issue #{issue.id}[/green]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not create knowledge base issue: {e}[/yellow]")


def _prompt_notes_migration(repo_path: Path, notes: list[Path], agents_path: Path) -> None:
    """Prompt user to migrate detected AI notes.

    Shows explanation, lists found files, and offers to migrate.
    If declined, shows the command to run later.

    Args:
        repo_path: Path to the repository root
        notes: List of detected AI note paths
        agents_path: Path to _agenttree directory
    """
    console.print("\n[cyan]═══ AI Notes Detected ═══[/cyan]")
    console.print("""
AgentTree keeps AI-generated documentation in a parallel git repository
(`_agenttree/notes/`) so agents don't clutter your main codebase with
their research files.
""")
    console.print(f"[bold]Found {len(notes)} AI-generated doc(s) that could be moved:[/bold]")
    for note in notes[:10]:  # Show first 10
        rel_path = note.relative_to(repo_path)
        console.print(f"  • {rel_path}")
    if len(notes) > 10:
        console.print(f"  [dim]... and {len(notes) - 10} more[/dim]")

    console.print("")
    if click.confirm("Would you like to migrate these now?", default=True):
        console.print("\n[cyan]Migrating files...[/cyan]")
        migrated = _migrate_notes(repo_path, notes, agents_path)
        console.print(f"\n[green]✓ Migrated {migrated} file(s) to _agenttree/notes/[/green]")

        # Commit the changes in main repo if any files were git mv'd
        if migrated > 0:
            console.print("[dim]Commit these changes in your main repo when ready.[/dim]")
    else:
        console.print("\n[dim]You can migrate later with:[/dim]")
        console.print("  [cyan]agenttree migrate-docs[/cyan]")


@click.command()
@click.option(
    "--worktrees-dir",
    type=click.Path(),
    help="Directory for worktrees (default: .worktrees/)",
)
@click.option("--project", help="Project name for tmux sessions")
def init(worktrees_dir: str | None, project: str | None) -> None:
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
    agents_path = repo_path / "_agenttree"
    try:
        agents_repo = AgentsRepository(repo_path)
        agents_repo.ensure_repo()
        console.print("[green]✓ _agenttree/ repository created[/green]")

        # Always create knowledge base population issue
        _create_knowledge_issue(repo_path)

        # Check for AI notes and offer migration
        ai_notes = _detect_ai_notes(repo_path)
        if ai_notes:
            _prompt_notes_migration(repo_path, ai_notes, agents_path)
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


@click.command()
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


@click.command()
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
            port = config.get_port_for_issue(agent_num)

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


@click.command()
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


@click.command("migrate-docs")
def migrate_docs() -> None:
    """Migrate AI-generated documentation to _agenttree/notes/.

    Scans for common AI notes patterns in your repository:
    - Files: *CLAUDE*.md, *AI*.md, *AGENT*.md, *NOTES*.md
    - Directories: docs/ai-notes/, docs/notes/, notes/

    Found files are moved to _agenttree/notes/ to keep your main
    codebase clean. Git-tracked files use 'git mv' to preserve history.

    Examples:
        agenttree migrate-docs
    """
    repo_path = Path.cwd()
    agents_path = repo_path / "_agenttree"

    if not agents_path.exists():
        console.print("[red]Error: _agenttree/ directory not found.[/red]")
        console.print("Run 'agenttree init' first.")
        sys.exit(1)

    console.print("[cyan]Scanning for AI-generated documentation...[/cyan]\n")

    ai_notes = _detect_ai_notes(repo_path)

    if not ai_notes:
        console.print("[green]✓ No AI notes files found to migrate.[/green]")
        console.print("[dim]Files matching patterns like *CLAUDE*.md, *AI*.md, etc. would be detected.[/dim]")
        return

    _prompt_notes_migration(repo_path, ai_notes, agents_path)
