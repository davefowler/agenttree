"""Agents repository management for AgentTree.

Manages the _agenttree/ git repository (separate from main project).
"""

from __future__ import annotations

import fcntl
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional, TYPE_CHECKING
import re

if TYPE_CHECKING:
    from agenttree.issues import Issue
    from agenttree.config import HostConfig, StageConfig

# Global lock file handle (kept open during sync)
_sync_lock_fd = None

from agenttree.frontmatter import (
    create_frontmatter,
    get_git_context,
    utc_now,
)


def slugify(text: str) -> str:
    """Convert text to a slug.

    Args:
        text: Text to slugify

    Returns:
        Slugified text
    """
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')


def sync_agents_repo(
    agents_dir: Path,
    pull_only: bool = False,
    commit_message: Optional[str] = None,
) -> bool:
    """Sync _agenttree repo with remote.

    Uses a file lock to prevent concurrent syncs from multiple agents.

    Args:
        agents_dir: Path to _agenttree directory
        pull_only: If True, only pull changes (for read operations)
        commit_message: Commit message for write operations

    Returns:
        True if sync succeeded, False otherwise
    """
    global _sync_lock_fd

    # Skip sync in containers - no SSH access, host handles syncing
    from agenttree.hooks import is_running_in_container
    if is_running_in_container():
        return False

    # Check if directory exists and is a git repo
    if not agents_dir.exists() or not (agents_dir / ".git").exists():
        return False

    # Acquire lock to prevent concurrent syncs
    lock_file = agents_dir / ".sync.lock"
    try:
        _sync_lock_fd = open(lock_file, "w")
        fcntl.flock(_sync_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (IOError, OSError):
        # Another sync is running, skip this one
        if _sync_lock_fd:
            _sync_lock_fd.close()
            _sync_lock_fd = None
        return False

    try:
        # First, commit any local changes (prevents "unstaged changes" error on pull)
        # Check for ANY changes (staged or unstaged)
        status_result = subprocess.run(
            ["git", "-C", str(agents_dir), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if status_result.stdout.strip():
            # There are changes - stage and commit them
            subprocess.run(
                ["git", "-C", str(agents_dir), "add", "-A"],
                capture_output=True,
                timeout=10,
            )
            message = commit_message or "Auto-sync: update issue data"
            subprocess.run(
                ["git", "-C", str(agents_dir), "commit", "-m", message],
                capture_output=True,
                text=True,
                timeout=10,
            )

        # Pull with merge (rebase causes issues with concurrent syncs)
        result = subprocess.run(
            ["git", "-C", str(agents_dir), "pull", "--no-rebase"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # If pull failed, check if it's a network issue or merge conflict
        if result.returncode != 0:
            # Check if it's just because we're offline or no remote
            if "Could not resolve host" in result.stderr or "no remote" in result.stderr:
                # Offline mode - continue without syncing
                return False
            elif "conflict" in result.stderr.lower():
                # Merge conflict - print error and fail
                print(f"Warning: Merge conflict in _agenttree repo: {result.stderr}")
                return False
            elif "local changes" in result.stderr.lower() or "overwritten" in result.stderr.lower():
                # Shouldn't happen after auto-commit, but try stash as fallback
                subprocess.run(["git", "-C", str(agents_dir), "stash", "--include-untracked"], capture_output=True, timeout=10)
                retry = subprocess.run(["git", "-C", str(agents_dir), "pull", "--no-rebase"], capture_output=True, timeout=30)
                subprocess.run(["git", "-C", str(agents_dir), "stash", "pop"], capture_output=True, timeout=10)
                if retry.returncode != 0:
                    return False
            else:
                # Other error - print warning but continue
                print(f"Warning: Failed to pull _agenttree repo: {result.stderr}")
                return False

        # If pull-only, run post-sync hooks then we're done
        if pull_only:
            from agenttree.controller_hooks import run_post_controller_hooks
            run_post_controller_hooks(agents_dir)
            return True

        # Push changes (local commits + any we just made)
        push_result = subprocess.run(
            ["git", "-C", str(agents_dir), "push"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if push_result.returncode != 0:
            # Push failed - could be offline or permission issue
            if "Could not resolve host" in push_result.stderr:
                print("Warning: Offline - changes committed locally but not pushed")
            else:
                print(f"Warning: Failed to push changes: {push_result.stderr}")
            return False

        # After successful sync, run configurable post-sync hooks
        from agenttree.controller_hooks import run_post_controller_hooks
        run_post_controller_hooks(agents_dir)

        return True

    except subprocess.TimeoutExpired:
        print("Warning: Git operation timed out")
        return False
    except Exception as e:
        print(f"Warning: Error syncing _agenttree repo: {e}")
        return False
    finally:
        # Always release the lock and reset the global
        if _sync_lock_fd:
            try:
                fcntl.flock(_sync_lock_fd, fcntl.LOCK_UN)
                _sync_lock_fd.close()
            except (IOError, OSError, ValueError):
                pass  # Already closed or invalid
            _sync_lock_fd = None


def check_controller_stages(agents_dir: Path) -> int:
    """Execute post_start hooks for issues in controller stages.

    Controller stages (host: controller) have their hooks executed by the host,
    not by agents. This is for operations agents can't do (like pushing/creating PRs).

    Called from host (sync, web server, etc.) on every sync.

    Args:
        agents_dir: Path to _agenttree directory

    Returns:
        Number of issues processed
    """
    # Bail early if running in a container - host operations only
    from agenttree.hooks import is_running_in_container, execute_enter_hooks
    from agenttree.config import load_config
    from agenttree.issues import Issue

    if is_running_in_container():
        return 0

    issues_dir = agents_dir / "issues"
    if not issues_dir.exists():
        return 0

    config = load_config()
    controller_stages = config.get_controller_stages()

    if not controller_stages:
        return 0

    import yaml

    processed = 0

    for issue_dir in issues_dir.iterdir():
        if not issue_dir.is_dir():
            continue

        issue_yaml = issue_dir / "issue.yaml"
        if not issue_yaml.exists():
            continue

        try:
            with open(issue_yaml) as f:
                data = yaml.safe_load(f)

            stage = data.get("stage", "")

            # Check if in a controller stage
            if stage in controller_stages:
                # Skip if hooks already executed for this stage
                hooks_executed_stage = data.get("controller_hooks_executed")
                if hooks_executed_stage == stage:
                    continue

                # Mark hooks as executed BEFORE running them to prevent infinite loop
                # (hooks may call sync_agents_repo which calls check_controller_stages)
                data["controller_hooks_executed"] = stage
                with open(issue_yaml, "w") as f:
                    yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)

                issue = Issue(**data)
                # Execute the post_start hooks for this stage (host side)
                execute_enter_hooks(issue, stage, data.get("substage"))

                processed += 1

        except Exception:
            continue

    return processed


def check_custom_agent_stages(agents_dir: Path) -> int:
    """Spawn custom agent hosts for issues in custom agent stages.

    Custom agent stages (host: <custom_agent_name>) have their agents
    spawned by the controller, similar to how controller stages work
    but instead of running hooks directly, we spawn a specialized agent.

    Called from host (sync, web server, etc.) on every sync.

    Args:
        agents_dir: Path to _agenttree directory

    Returns:
        Number of agents spawned
    """
    from agenttree.hooks import is_running_in_container
    from agenttree.config import load_config
    from agenttree.issues import Issue

    # Bail early if running in a container - host operations only
    if is_running_in_container():
        return 0

    issues_dir = agents_dir / "issues"
    if not issues_dir.exists():
        return 0

    config = load_config()
    custom_agent_stages = config.get_custom_agent_stages()

    if not custom_agent_stages:
        return 0

    import yaml
    from rich.console import Console
    from agenttree.tmux import session_exists
    console = Console()

    spawned = 0

    for issue_dir in issues_dir.iterdir():
        if not issue_dir.is_dir():
            continue

        issue_yaml = issue_dir / "issue.yaml"
        if not issue_yaml.exists():
            continue

        try:
            with open(issue_yaml) as f:
                data = yaml.safe_load(f)

            stage = data.get("stage", "")

            # Check if in a custom agent stage
            if stage in custom_agent_stages:
                # Get the stage config to find the host name
                stage_config = config.get_stage(stage)
                if not stage_config:
                    continue

                host_name = stage_config.host
                agent_config = config.get_agent_host(host_name)
                if not agent_config:
                    console.print(f"[yellow]Custom agent host '{host_name}' not found in config[/yellow]")
                    continue

                # Check if custom agent is already running (runtime check, not cached marker)
                issue_id = data.get("id", "")
                custom_agent_session = f"{config.project}-{host_name}-{issue_id}"

                from agenttree.tmux import is_claude_running, send_message

                if session_exists(custom_agent_session):
                    # Session exists - check if Claude is still running
                    if is_claude_running(custom_agent_session):
                        # Ping the agent to let it know about the stage
                        result = send_message(
                            custom_agent_session,
                            f"Stage is now {stage}. Run `agenttree next` for your instructions."
                        )
                        if result == "sent":
                            console.print(f"[dim]Pinged {host_name} agent for issue #{issue_id}[/dim]")
                        continue
                    else:
                        # Session exists but Claude exited - need to restart
                        console.print(f"[yellow]{host_name} agent session exists but Claude exited, restarting...[/yellow]")
                        # Fall through to spawn logic below

                issue = Issue(**data)
                console.print(f"[cyan]Starting {host_name} agent for issue #{issue.id} at stage {stage}...[/cyan]")

                # Use agenttree start --host to spawn the agent
                import subprocess
                result = subprocess.run(
                    ["agenttree", "start", issue.id, "--host", host_name, "--skip-preflight"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    console.print(f"[green]✓ Started {host_name} agent for issue #{issue.id}[/green]")
                    spawned += 1
                else:
                    console.print(f"[red]Failed to start {host_name} agent for issue #{issue.id}[/red]")
                    if result.stderr:
                        console.print(f"[dim]{result.stderr[:200]}[/dim]")

        except Exception as e:
            from rich.console import Console
            Console().print(f"[yellow]Error checking issue for custom agent: {e}[/yellow]")
            continue

    return spawned


def _update_issue_stage_direct(yaml_path: Path, data: dict, new_stage: str, new_substage: str | None = None) -> None:
    """Update issue stage directly without triggering sync (to avoid recursion).

    Used by check_merged_prs to avoid infinite loop since update_issue_stage
    calls sync_agents_repo which calls check_merged_prs.

    Args:
        yaml_path: Path to issue.yaml
        data: Issue data dict
        new_stage: Target stage name
        new_substage: Target substage (required for stages with substages like 'implement')
    """
    from datetime import datetime, timezone
    import yaml as yaml_module

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["stage"] = new_stage
    data["substage"] = new_substage
    data["updated"] = now

    # Add history entry
    if "history" not in data:
        data["history"] = []
    data["history"].append({
        "stage": new_stage,
        "substage": new_substage,
        "timestamp": now,
        "agent": None,
    })

    with open(yaml_path, "w") as f:
        yaml_module.dump(data, f, default_flow_style=False, sort_keys=False)


def check_merged_prs(agents_dir: Path) -> int:
    """Check for issues at implementation_review whose PRs were merged/closed externally.

    If a human merges or closes a PR via GitHub UI or `gh pr merge` instead of
    using `agenttree approve`, this function detects it and advances the issue:
    - Merged PR → advances to `accepted`
    - Closed (not merged) PR → advances to `not_doing`

    Called from host during sync.

    Args:
        agents_dir: Path to _agenttree directory

    Returns:
        Number of issues advanced
    """
    from agenttree.hooks import is_running_in_container
    if is_running_in_container():
        return 0

    issues_dir = agents_dir / "issues"
    if not issues_dir.exists():
        return 0

    import yaml
    from rich.console import Console
    console = Console()

    issues_advanced = 0

    for issue_dir in issues_dir.iterdir():
        if not issue_dir.is_dir():
            continue

        issue_yaml = issue_dir / "issue.yaml"
        if not issue_yaml.exists():
            continue

        try:
            with open(issue_yaml) as f:
                data = yaml.safe_load(f)

            # Only check issues at implementation_review WITH a PR
            if data.get("stage") != "implementation_review":
                continue
            pr_number = data.get("pr_number")
            if not pr_number:
                continue

            issue_id = data.get("id", "")
            if not issue_id:
                continue

            # Check PR status via gh CLI
            result = subprocess.run(
                ["gh", "pr", "view", str(pr_number), "--json", "state,mergedAt"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode != 0:
                continue

            import json
            pr_data = json.loads(result.stdout)
            state = pr_data.get("state", "").upper()
            merged_at = pr_data.get("mergedAt")

            if state == "MERGED" or merged_at:
                # PR was merged externally - advance to accepted
                console.print(f"[green]PR #{pr_number} was merged externally, advancing issue #{issue_id} to accepted[/green]")
                _update_issue_stage_direct(issue_yaml, data, "accepted")
                issues_advanced += 1
                # Clean up the agent since we bypassed normal hooks
                from agenttree.hooks import cleanup_issue_agent
                from agenttree.issues import Issue
                cleanup_issue_agent(Issue(**data))
            elif state == "CLOSED":
                # PR was closed without merging - advance to not_doing
                console.print(f"[yellow]PR #{pr_number} was closed without merge, advancing issue #{issue_id} to not_doing[/yellow]")
                _update_issue_stage_direct(issue_yaml, data, "not_doing")
                issues_advanced += 1
                # Clean up the agent since we bypassed normal hooks
                from agenttree.hooks import cleanup_issue_agent
                from agenttree.issues import Issue
                cleanup_issue_agent(Issue(**data))

        except subprocess.TimeoutExpired:
            console.print(f"[yellow]Timeout checking PR status[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Error checking PR: {e}[/yellow]")
            continue

    return issues_advanced


def check_ci_status(agents_dir: Path) -> int:
    """Check CI status for issues at implementation_review and notify agents on failure.

    For issues at implementation_review with a PR:
    - Checks CI status via get_pr_checks()
    - If CI failed: writes ci_feedback.md, sends tmux message, transitions to implement

    Called from host during sync.

    Args:
        agents_dir: Path to _agenttree directory

    Returns:
        Number of issues with CI failures processed
    """
    from agenttree.hooks import is_running_in_container
    if is_running_in_container():
        return 0

    issues_dir = agents_dir / "issues"
    if not issues_dir.exists():
        return 0

    import yaml
    from rich.console import Console
    from agenttree.github import get_pr_checks, get_pr_comments, get_check_failed_logs
    from agenttree.state import get_active_agent
    from agenttree.config import load_config
    from agenttree.tmux import TmuxManager

    console = Console()
    issues_notified = 0

    for issue_dir in issues_dir.iterdir():
        if not issue_dir.is_dir():
            continue

        issue_yaml = issue_dir / "issue.yaml"
        if not issue_yaml.exists():
            continue

        try:
            with open(issue_yaml) as f:
                data = yaml.safe_load(f)

            # Only check issues at implementation_review WITH a PR
            if data.get("stage") != "implementation_review":
                continue
            pr_number = data.get("pr_number")
            if not pr_number:
                continue

            # Skip if already notified for this CI failure
            if data.get("ci_notified"):
                continue

            issue_id = data.get("id", "")
            if not issue_id:
                continue

            # Check CI status
            checks = get_pr_checks(pr_number)
            if not checks:
                # No checks yet, skip
                continue

            # Check if any check is still pending
            any_pending = any(check.state == "PENDING" for check in checks)
            if any_pending:
                # CI still running, wait
                continue

            # Check if any check failed
            failed_checks = [
                check for check in checks
                if check.state == "FAILURE"
            ]

            if not failed_checks:
                # All checks passed, nothing to do
                continue

            # CI failed - create feedback file with logs and review comments
            feedback_content = "# CI Failure Report\n\n"
            feedback_content += f"PR #{pr_number} has failing CI checks:\n\n"
            for check in checks:
                status = "PASSED" if check.state == "SUCCESS" else "FAILED"
                feedback_content += f"- **{check.name}**: {status}\n"

            # Fetch and include failed logs for each failed check
            for check in failed_checks:
                logs = get_check_failed_logs(check)
                if logs:
                    feedback_content += f"\n---\n\n## Failed Logs: {check.name}\n\n```\n{logs}\n```\n"

            # Fetch and include PR review comments
            comments = get_pr_comments(pr_number)
            if comments:
                feedback_content += "\n---\n\n## Review Comments\n\n"
                for comment in comments:
                    feedback_content += f"### From @{comment.author}\n\n"
                    feedback_content += f"{comment.body}\n\n"

            feedback_content += "\n---\n\nPlease fix these issues and run `agenttree next` to re-submit.\n"

            feedback_file = issue_dir / "ci_feedback.md"
            feedback_file.write_text(feedback_content)

            console.print(f"[yellow]CI failed for PR #{pr_number}, notifying issue #{issue_id}[/yellow]")

            # Try to send tmux message to agent
            agent = get_active_agent(issue_id)
            if agent:
                try:
                    config = load_config()
                    tmux_manager = TmuxManager(config)
                    if tmux_manager.is_issue_running(agent.tmux_session):
                        message = f"CI failed for PR #{pr_number}. See ci_feedback.md for details. Run `agenttree next` after fixing."
                        tmux_manager.send_message_to_issue(agent.tmux_session, message)
                        console.print(f"[green]✓ Notified agent for issue #{issue_id}[/green]")
                except Exception as e:
                    console.print(f"[yellow]Could not notify agent: {e}[/yellow]")

            # Transition issue back to implement.debug stage for CI fix
            _update_issue_stage_direct(issue_yaml, data, "implement", "debug")
            console.print(f"[yellow]Issue #{issue_id} moved back to implement.debug stage for CI fix[/yellow]")

            issues_notified += 1

        except Exception as e:
            console.print(f"[yellow]Error checking CI status: {e}[/yellow]")
            continue

    return issues_notified


def push_pending_branches(agents_dir: Path) -> int:
    """Push branches for issues that have unpushed commits.

    Called from host (sync, web server, etc.) to push branches for issues
    where agents have committed but couldn't push from containers.

    Detects unpushed commits by checking git directly.
    Tries regular push first, falls back to force push if histories diverged.

    Bails early if running inside a container.

    Args:
        agents_dir: Path to _agenttree directory

    Returns:
        Number of branches pushed
    """
    from agenttree.hooks import is_running_in_container
    if is_running_in_container():
        return 0

    issues_dir = agents_dir / "issues"
    if not issues_dir.exists():
        return 0

    import yaml
    from rich.console import Console
    console = Console()

    branches_pushed = 0

    for issue_dir in issues_dir.iterdir():
        if not issue_dir.is_dir():
            continue

        issue_yaml = issue_dir / "issue.yaml"
        if not issue_yaml.exists():
            continue

        try:
            with open(issue_yaml) as f:
                data = yaml.safe_load(f)

            issue_id = data.get("id", "")
            branch = data.get("branch")
            worktree_dir = data.get("worktree_dir")

            if not branch or not worktree_dir:
                continue

            worktree_path = Path(worktree_dir)
            if not worktree_path.exists():
                continue

            # Check git for unpushed commits
            check_result = subprocess.run(
                ["git", "-C", str(worktree_path), "log", f"origin/{branch}..HEAD", "--oneline"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if check_result.returncode != 0 or not check_result.stdout.strip():
                continue

            console.print(f"[dim]Pushing branch {branch} for issue #{issue_id}...[/dim]")

            # Try regular push first
            result = subprocess.run(
                ["git", "-C", str(worktree_path), "push", "-u", "origin", branch],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                # Check if it's a diverged history (needs force push)
                if "divergent" in result.stderr or "rejected" in result.stderr or "non-fast-forward" in result.stderr:
                    console.print(f"[dim]Histories diverged, force pushing...[/dim]")
                    result = subprocess.run(
                        ["git", "-C", str(worktree_path), "push", "--force-with-lease", "-u", "origin", branch],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )

            if result.returncode == 0:
                console.print(f"[green]✓ Pushed branch {branch} for issue #{issue_id}[/green]")
                branches_pushed += 1
            else:
                console.print(f"[red]Failed to push branch {branch}: {result.stderr}[/red]")

        except subprocess.TimeoutExpired:
            console.print(f"[yellow]Push timed out for issue #{issue_id}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Error pushing issue #{issue_id}: {e}[/yellow]")

    return branches_pushed


class AgentsRepository:
    """Manages the _agenttree/ git repository."""

    def __init__(self, project_path: Path):
        """Initialize agents repository manager.

        Args:
            project_path: Path to the main project repository
        """
        self.project_path = project_path
        self.agents_path = project_path / "_agenttree"
        self.project_name = project_path.name

    def ensure_repo(self) -> None:
        """Ensure _agenttree/ repo exists, create if needed."""
        # Check if _agenttree/.git exists
        if (self.agents_path / ".git").exists():
            return

        # Ensure gh CLI is authenticated
        self._ensure_gh_cli()

        # Create GitHub repo
        self._create_github_repo()

        # Clone it locally
        self._clone_repo()

        # Add to parent .gitignore
        self._add_to_gitignore()

    def _ensure_gh_cli(self) -> None:
        """Check gh CLI is installed and authenticated."""
        if not shutil.which("gh"):
            raise RuntimeError(
                "GitHub CLI (gh) not found.\n\n"
                "Install: https://cli.github.com/\n"
                "  macOS:   brew install gh\n"
                "  Linux:   See https://github.com/cli/cli#installation\n"
                "  Windows: See https://github.com/cli/cli#installation\n"
            )

        # Check auth status
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Not authenticated with GitHub.\n\n"
                "Run: gh auth login\n\n"
                "This will open your browser to authenticate.\n"
                "AgentTree needs GitHub access to:\n"
                "  - Create agent notes repository\n"
                "  - Fetch issues\n"
                "  - Create pull requests\n"
                "  - Monitor CI status\n"
            )

    def _create_github_repo(self) -> None:
        """Create GitHub repo for agents."""
        repo_name = f"{self.project_name}_agenttree"

        # Check if repo already exists
        result = subprocess.run(
            ["gh", "repo", "view", repo_name],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            # Repo exists
            print(f"GitHub repo {repo_name} already exists")
            return

        # Create new private repo
        print(f"Creating GitHub repo: {repo_name}")
        subprocess.run(
            [
                "gh",
                "repo",
                "create",
                repo_name,
                "--private",
                "--description",
                f"AgentTree issue tracking for {self.project_name}",
            ],
            check=True,
        )

    def _clone_repo(self) -> None:
        """Clone agenttree repo locally."""
        repo_name = f"{self.project_name}_agenttree"

        # Get current GitHub user
        result = subprocess.run(
            ["gh", "api", "user", "-q", ".login"],
            capture_output=True,
            text=True,
            check=True,
        )
        username = result.stdout.strip()

        print(f"Cloning {repo_name} to _agenttree/")

        # Clone
        subprocess.run(
            ["gh", "repo", "clone", f"{username}/{repo_name}", str(self.agents_path)],
            check=True,
        )

        # Initialize structure
        self._initialize_structure()

    def _initialize_structure(self) -> None:
        """Create initial folder structure and templates."""
        print("Initializing _agenttree/ structure...")

        # Create directories
        (self.agents_path / "templates").mkdir(exist_ok=True)
        (self.agents_path / "specs" / "architecture").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "specs" / "features").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "specs" / "patterns").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "tasks").mkdir(exist_ok=True)
        (self.agents_path / "tasks" / "archive").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "rfcs").mkdir(exist_ok=True)
        (self.agents_path / "rfcs" / "archive").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "plans").mkdir(exist_ok=True)
        (self.agents_path / "plans" / "archive").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "knowledge").mkdir(exist_ok=True)

        # Create README
        self._create_readme()

        # Create templates
        self._create_templates()

        # Create knowledge files
        self._create_knowledge_files()

        # Create AGENTS.md instructions
        self._create_agents_instructions()

        # Commit
        subprocess.run(["git", "add", "."], cwd=self.agents_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initialize agents repository"],
            cwd=self.agents_path,
            check=True,
        )
        subprocess.run(["git", "push"], cwd=self.agents_path, check=True)

        print("✓ _agenttree/ repository initialized")

    def _create_readme(self) -> None:
        """Create main README."""
        readme = self.agents_path / "README.md"
        readme.write_text(
            f"""# AI Notes for {self.project_name}

This repository contains AI-generated content managed by AgentTree.

## Structure

- `templates/` - Templates for consistency (feature specs, RFCs, task logs)
- `specs/` - Living documentation (architecture, features, patterns)
- `tasks/` - Task execution logs by agent
- `rfcs/` - Design proposals (Request for Comments)
- `plans/` - Planning documents
- `knowledge/` - Accumulated wisdom (gotchas, decisions, onboarding)

## Quick Links

- [Architecture](specs/architecture/)
- [Features](specs/features/)
- [Knowledge Base](knowledge/)
- [Recent Tasks](tasks/)

## For Agents

See [AGENTS.md](AGENTS.md) for instructions on maintaining this repository.

---

*Auto-managed by AgentTree*
"""
        )

    def _create_templates(self) -> None:
        """Create template files."""
        templates_dir = self.agents_path / "templates"

        # Feature spec template
        (templates_dir / "feature-spec.md").write_text(
            """# Feature: {Name}

**Issue:** #{number}
**Status:** Planning | In Progress | Complete

## Overview

[What this feature does - user perspective]

## User Stories

- As a {user type}, I want to {action} so that {benefit}

## Technical Approach

[High-level how it works - link to RFC if applicable]

**Related RFC:** [RFC-XXX](../rfcs/XXX-name.md) (if applicable)

## API/Interface

[Endpoints, functions, UI components]

## Implementation Notes

[Things to know while building]

## Testing

[How to verify it works]

## Related

- Issue: #{number}
- PR: #{number}
- Specs: [link]
"""
        )

        # RFC template
        (templates_dir / "rfc.md").write_text(
            """# RFC-{number}: {Title}

**Author:** {agent-name}
**Date:** {YYYY-MM-DD}
**Status:** Proposed | Accepted | Rejected

## Summary

[2-3 sentences: what you're proposing]

## Motivation

**Current State:**
[What exists now]

**Problem:**
[What's wrong with current state]

**Proposed Solution:**
[High-level approach]

## Detailed Design

[How it works - diagrams, pseudocode, API designs]

## Drawbacks

[Why we might NOT do this]

## Alternatives Considered

### Option 1: {Name}
- **Pros:**
- **Cons:**
- **Why not chosen:**

### Option 2: {Name}
- **Pros:**
- **Cons:**
- **Why not chosen:**

## Unresolved Questions

- [ ] Question 1
- [ ] Question 2

## Implementation Plan

[If accepted, how we'll build it]

## Timeline

[Estimated timeline if applicable]
"""
        )

        # Task log template
        (templates_dir / "task-log.md").write_text(
            """# Task: {title}

**Date:** {date}
**Agent:** {agent}
**Issue:** #{issue_num}
**Status:** 🔄 In Progress

## Context

{description}

## Work Log

### {timestamp}

[Log what you're doing, decisions made, blockers encountered]

## Learnings

[Any gotchas discovered, patterns learned]

## Related

- Issue: {issue_url}
- Spec: [link to relevant spec]
"""
        )

        # Investigation template
        (templates_dir / "investigation.md").write_text(
            """# Investigation: {Title}

**Date:** {YYYY-MM-DD}
**Investigator:** {agent-name}
**Issue:** #{number} (if applicable)

## Problem

[What's broken or unclear]

## Hypothesis

[What you think is causing it]

## Investigation Steps

### Step 1: {Description}
**What:** [What you did]
**Result:** [What you found]

### Step 2: {Description}
**What:** [What you did]
**Result:** [What you found]

## Root Cause

[What actually caused the issue]

## Solution

[How to fix it]

## Prevention

[How to prevent this in the future]
"""
        )

    def _create_knowledge_files(self) -> None:
        """Create initial knowledge base files."""
        knowledge_dir = self.agents_path / "knowledge"

        # gotchas.md
        (knowledge_dir / "gotchas.md").write_text(
            """# Known Gotchas

This file contains known issues, workarounds, and "gotchas" discovered by agents.

## Format

```markdown
## {Title}

**Problem:** [What goes wrong]
**Solution:** [How to fix/avoid it]
**Discovered:** {YYYY-MM-DD} by {agent-name} (#{issue})
**Related:** [link to task log or spec]
```

---

*Agents: Add your discoveries here as you find them!*
"""
        )

        # decisions.md (Architecture Decision Records)
        (knowledge_dir / "decisions.md").write_text(
            """# Architecture Decision Records (ADRs)

This file documents key architectural decisions and their rationale.

## Format

```markdown
## ADR-{number}: {Title}

**Date:** {YYYY-MM-DD}
**Decided by:** {agent/human}
**Status:** Accepted | Superseded | Deprecated

**Context:**
[Why we needed to make this decision]

**Decision:**
[What we decided]

**Consequences:**
- ✅ Positive consequence
- ❌ Negative consequence
```

---

*Agents: Document major decisions here!*
"""
        )

        # onboarding.md
        (knowledge_dir / "onboarding.md").write_text(
            f"""# Onboarding Guide for {self.project_name}

*This file is auto-generated and maintained by agents.*

## Quick Start

1. **Architecture Overview:** See [specs/architecture/](../specs/architecture/)
2. **Key Patterns:** See [specs/patterns/](../specs/patterns/)
3. **Common Gotchas:** See [gotchas.md](gotchas.md)
4. **Decisions Made:** See [decisions.md](decisions.md)

## Project Structure

[Agents: Describe the codebase structure]

## Development Workflow

[Agents: Document how to develop locally]

## Common Tasks

[Agents: Document common development tasks]

## Testing

[Agents: Document testing approach]

## Deployment

[Agents: Document deployment process]

---

*Updated: {datetime.now().strftime("%Y-%m-%d")}*
"""
        )

    def _create_agents_instructions(self) -> None:
        """Create AGENTS.md with instructions for AI agents."""
        (self.agents_path / "AGENTS.md").write_text(
            """# Agent Instructions

## 📋 Check the tasks/ folder for pending work!

Tasks are stored as dated .md files (e.g., `tasks/2025-01-15-fix-login-bug.md`).
Work on the **oldest** task first. When done, it moves to `tasks/archive/`.

## Documentation Structure

Your work is tracked in this `_agenttree/` repository (separate from main code).

### During Development

**Update your task log:**

File: `tasks/agent-{N}/YYYY-MM-DD-task.md`

```markdown
## Work Log

### 2025-01-15 14:30
Started investigating the timeout issue. Found it's in session.go...

### 2025-01-15 15:45
Fixed race condition by adding mutex. Added test.
```

**Found a gotcha?** Add to `knowledge/gotchas.md`:

```markdown
## Session Store Race Condition
**Problem:** Default session store isn't thread-safe
**Solution:** Use sync.Mutex or Redis
**Discovered:** 2025-01-15 (agent-1, #42)
```

**Changed architecture?** Update relevant file in `specs/architecture/`

**Added a pattern?** Document in `specs/patterns/`

### Templates

Use templates in `templates/` for consistency:
- `feature-spec.md` - For documenting features
- `rfc.md` - For design proposals
- `task-log.md` - Format for your task logs
- `investigation.md` - For bug investigations

### On Completion

Run `./scripts/submit.sh` which will:
✓ Create PR
✓ Mark task as complete
✓ Archive task log automatically

## File Organization

- `specs/` - **Living docs** (keep updated as code changes)
- `tasks/` - **Historical logs** (archive after completion)
- `rfcs/` - **Design proposals** (for major decisions)
- `plans/` - **Planning docs** (for complex projects)
- `knowledge/` - **Shared wisdom** (gotchas, decisions, onboarding)

## Important: Do NOT Merge Your Own PR

PRs are reviewed and merged by humans using `agenttree approve`. Never use `gh pr merge` directly—this bypasses the workflow and leaves issues stuck at `implementation_review`.

## Questions?

See [README.md](README.md) for structure overview.
"""
        )

    def _add_to_gitignore(self) -> None:
        """Add _agenttree/ and .worktrees/ to parent .gitignore."""
        gitignore = self.project_path / ".gitignore"

        entries_to_add = []

        if gitignore.exists():
            content = gitignore.read_text()
            if "_agenttree/" not in content:
                entries_to_add.append("_agenttree/")
            if ".worktrees/" not in content:
                entries_to_add.append(".worktrees/")

            if entries_to_add:
                with open(gitignore, "a") as f:
                    f.write("\n# AgentTree directories\n")
                    for entry in entries_to_add:
                        f.write(f"{entry}\n")
        else:
            gitignore.write_text("# AgentTree directories\n_agenttree/\n.worktrees/\n")
            entries_to_add = ["_agenttree/", ".worktrees/"]

        if entries_to_add:
            print(f"✓ Added {', '.join(entries_to_add)} to .gitignore")

    def create_task_file(
        self, agent_num: int, issue_num: int, issue_title: str, issue_body: str, issue_url: str
    ) -> Path:
        """Create task file with frontmatter.

        Args:
            agent_num: Agent number
            issue_num: Issue number
            issue_title: Issue title
            issue_body: Issue description
            issue_url: Issue URL

        Returns:
            Path to created task file
        """
        date = datetime.now().strftime("%Y-%m-%d")
        slug = slugify(issue_title)
        agent_dir = self.agents_path / "tasks" / f"agent-{agent_num}"
        agent_dir.mkdir(exist_ok=True)

        task_file = agent_dir / f"{date}-{slug}.md"
        task_id = f"agent-{agent_num}-{date}-{slug}"

        # Get git context from project repo
        git_ctx = get_git_context(self.project_path)

        # Create frontmatter
        frontmatter = {
            "document_type": "task_log",
            "version": 1,
            "task_id": task_id,
            "issue_number": issue_num,
            "issue_title": issue_title,
            "issue_url": issue_url,
            "agent": f"agent-{agent_num}",
            "created_at": utc_now(),
            "started_at": utc_now(),
            "completed_at": None,
            "status": "in_progress",
            **git_ctx,
            "work_branch": f"agent-{agent_num}/work",
            "commits": [],
            "pr_number": None,
            "pr_url": None,
            "pr_status": None,
            "spec_file": f"specs/features/issue-{issue_num}.md",
            "context_file": f"context/agent-{agent_num}/issue-{issue_num}.md",
            "files_changed": [],
            "tags": [],
        }

        # Create content
        content = create_frontmatter(frontmatter)
        content += f"# Task: {issue_title}\n\n"
        content += f"## Context\n\n{issue_body}\n\n"
        content += f"## Work Log\n\n"
        content += f"### {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        content += f"Task started.\n"

        task_file.write_text(content)

        # Commit
        self._commit(f"Start task: {issue_title}")

        return task_file

    def create_spec_file(
        self, issue_num: int, issue_title: str, issue_body: str, issue_url: str
    ) -> None:
        """Create spec file with frontmatter from issue if it doesn't exist.

        Args:
            issue_num: Issue number
            issue_title: Issue title
            issue_body: Issue description
            issue_url: Issue URL
        """
        spec_file = self.agents_path / "specs" / "features" / f"issue-{issue_num}.md"

        if spec_file.exists():
            return  # Already exists

        # Get git context from project repo
        git_ctx = get_git_context(self.project_path)

        # Create frontmatter
        frontmatter = {
            "document_type": "spec",
            "version": 1,
            "spec_type": "feature",
            "feature_name": issue_title,
            "issue_number": issue_num,
            "issue_url": issue_url,
            "status": "planning",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "implemented_at": None,
            **git_ctx,
            "implemented_in_pr": None,
            "related_commits": [],
            "rfc": None,
            "related_specs": [],
            "tasks": [],
            "tags": [],
            "contributors": [],
        }

        # Create content
        content = create_frontmatter(frontmatter)
        content += f"# {issue_title}\n\n"
        content += f"## Description\n\n{issue_body}\n\n"
        content += f"## Implementation Notes\n\n"
        content += f"(Agents will add notes here as work progresses)\n\n"
        content += f"## Related\n\n"
        content += f"- Issue: [#{issue_num}]({issue_url})\n"

        spec_file.write_text(content)
        self._commit(f"Add spec for issue #{issue_num}")

    def create_context_summary(
        self, agent_num: int, issue_num: int, issue_title: str, task_id: str
    ) -> Path:
        """Create pre-filled context summary for task re-engagement.

        Args:
            agent_num: Agent number
            issue_num: Issue number
            issue_title: Issue title
            task_id: Task ID (e.g., agent-1-2026-01-04-fix-auth)

        Returns:
            Path to created context summary file
        """
        context_dir = self.agents_path / "context" / f"agent-{agent_num}"
        context_dir.mkdir(parents=True, exist_ok=True)

        context_file = context_dir / f"issue-{issue_num}.md"

        # Don't overwrite existing context summary
        if context_file.exists():
            return context_file

        # Get git context from project repo
        git_ctx = get_git_context(self.project_path)

        # Create frontmatter (mostly pre-filled, agent fills content)
        frontmatter = {
            "document_type": "context_summary",
            "version": 1,
            "task_id": task_id,
            "issue_number": issue_num,
            "agent": f"agent-{agent_num}",
            "task_started": utc_now(),
            "summary_created": None,  # Filled when agent completes task
            **git_ctx,
            "work_branch": f"agent-{agent_num}/work",
            "final_commit": None,  # Filled on completion
            "pr_number": None,
            "pr_status": None,
            "commits_count": 0,
            "files_changed_count": 0,
            "key_files": [],
            "task_log": f"tasks/agent-{agent_num}/{datetime.now().strftime('%Y-%m-%d')}-{slugify(issue_title)}.md",
            "spec_file": f"specs/features/issue-{issue_num}.md",
            "notes_created": [],
            "tags": [],
        }

        # Create content with template sections
        content = create_frontmatter(frontmatter)
        content += f"# Context Summary: {issue_title}\n\n"
        content += f"## What Was Done\n\n"
        content += f"<!-- Fill this in as you work, or at task completion -->\n\n"
        content += f"## Key Decisions\n\n"
        content += f"<!-- Document important architectural/design decisions -->\n\n"
        content += f"## Gotchas Discovered\n\n"
        content += f"<!-- Any non-obvious issues you hit -->\n\n"
        content += f"## Key Files Modified\n\n"
        content += f"<!-- List main files changed with brief descriptions -->\n\n"
        content += f"## For Resuming\n\n"
        content += f"<!-- If someone (including you) needs to resume this task later, what should they know? -->\n\n"

        context_file.write_text(content)

        # Commit
        self._commit(f"Create context summary for issue #{issue_num}")

        return context_file

    def mark_task_complete(self, agent_num: int, pr_num: int) -> None:
        """Mark task as complete and prepare for archival.

        Args:
            agent_num: Agent number
            pr_num: Pull request number
        """
        # Find most recent task file for this agent
        agent_dir = self.agents_path / "tasks" / f"agent-{agent_num}"
        if not agent_dir.exists():
            return

        task_files = sorted(agent_dir.glob("*.md"), reverse=True)
        if not task_files:
            return

        task_file = task_files[0]  # Most recent

        # Append completion info
        with open(task_file, "a") as f:
            f.write(f"\n\n## Status: ✅ Completed\n\n")
            f.write(f"**PR:** #{pr_num}\n")
            f.write(f"**Completed:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

        self._commit(f"Mark task complete: {task_file.name}")

    def archive_task(self, agent_num: int) -> None:
        """Archive most recent completed task.

        Args:
            agent_num: Agent number
        """
        agent_dir = self.agents_path / "tasks" / f"agent-{agent_num}"
        if not agent_dir.exists():
            return

        # Find most recent task
        task_files = sorted(agent_dir.glob("*.md"), reverse=True)
        if not task_files:
            return

        task_file = task_files[0]

        # Extract year-month from filename
        year_month = task_file.name[:7]  # YYYY-MM

        # Create archive directory
        archive_dir = self.agents_path / "tasks" / "archive" / year_month
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Move to archive
        new_name = f"agent-{agent_num}-{task_file.name[11:]}"  # Skip YYYY-MM-DD-
        archive_path = archive_dir / new_name

        shutil.move(task_file, archive_path)

        self._commit(f"Archive task: {new_name}")

    def _commit(self, message: str) -> None:
        """Commit changes to agents/ repo.

        Args:
            message: Commit message
        """
        try:
            subprocess.run(["git", "add", "."], cwd=self.agents_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.agents_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "push"], cwd=self.agents_path, check=True, capture_output=True
            )
        except subprocess.CalledProcessError:
            # Nothing to commit or push failed - that's okay
            pass
