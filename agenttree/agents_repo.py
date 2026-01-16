"""Agents repository management for AgentTree.

Manages the _agenttree/ git repository (separate from main project).
"""

import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional
import re

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

    Args:
        agents_dir: Path to _agenttree directory
        pull_only: If True, only pull changes (for read operations)
        commit_message: Commit message for write operations

    Returns:
        True if sync succeeded, False otherwise
    """
    # Skip sync in containers - no SSH access, host handles syncing
    from agenttree.hooks import is_running_in_container
    if is_running_in_container():
        return False

    # Check if directory exists and is a git repo
    if not agents_dir.exists() or not (agents_dir / ".git").exists():
        return False

    try:
        # First, commit any local changes (prevents "unstaged changes" error on pull)
        subprocess.run(
            ["git", "-C", str(agents_dir), "add", "-A"],
            check=False,
            capture_output=True,
            timeout=10,
        )

        # Check if there are staged changes to commit
        diff_result = subprocess.run(
            ["git", "-C", str(agents_dir), "diff", "--cached", "--quiet"],
            capture_output=True,
            timeout=10,
        )

        # Commit local changes first (if any)
        if diff_result.returncode != 0:
            message = commit_message or "Auto-sync: update issue data"
            subprocess.run(
                ["git", "-C", str(agents_dir), "commit", "-m", message],
                capture_output=True,
                text=True,
                timeout=10,
            )

        # Now pull with rebase (safe because local changes are committed)
        result = subprocess.run(
            ["git", "-C", str(agents_dir), "pull", "--rebase"],
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
            else:
                # Other error - print warning but continue
                print(f"Warning: Failed to pull _agenttree repo: {result.stderr}")
                return False

        # If pull-only, check for pending pushes and PRs, then we're done
        if pull_only:
            push_pending_branches(agents_dir)
            check_pending_prs(agents_dir)
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

        # After successful sync, push pending branches and check for issues needing PRs
        push_pending_branches(agents_dir)
        check_pending_prs(agents_dir)

        return True

    except subprocess.TimeoutExpired:
        print("Warning: Git operation timed out")
        return False
    except Exception as e:
        print(f"Warning: Error syncing _agenttree repo: {e}")
        return False


def check_pending_prs(agents_dir: Path) -> int:
    """Check for issues at implementation_review without PRs and create them.

    Called from host (sync, web server, etc.) to create PRs for issues
    where agents couldn't push from containers.

    Bails early if running inside a container (containers can't push anyway).

    Args:
        agents_dir: Path to _agenttree directory

    Returns:
        Number of PRs created
    """
    # Bail early if running in a container - no point checking since we can't push
    from agenttree.hooks import is_running_in_container
    if is_running_in_container():
        return 0

    issues_dir = agents_dir / "issues"
    if not issues_dir.exists():
        return 0

    import yaml

    prs_created = 0

    for issue_dir in issues_dir.iterdir():
        if not issue_dir.is_dir():
            continue

        issue_yaml = issue_dir / "issue.yaml"
        if not issue_yaml.exists():
            continue

        try:
            with open(issue_yaml) as f:
                data = yaml.safe_load(f)

            # Check if at implementation_review without PR
            if data.get("stage") == "implementation_review" and not data.get("pr_number"):
                issue_id = data.get("id", "")
                if issue_id:
                    from agenttree.hooks import ensure_pr_for_issue
                    if ensure_pr_for_issue(str(issue_id)):
                        prs_created += 1
        except Exception:
            continue

    return prs_created


def push_pending_branches(agents_dir: Path) -> int:
    """Push branches for issues with needs_push=true.

    Called from host (sync, web server, etc.) to push branches for issues
    where agents have committed but couldn't push from containers.

    Tries regular push first, falls back to force push if histories diverged.
    Clears needs_push flag after successful push.

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

            # Check if needs_push is set
            if not data.get("needs_push"):
                continue

            issue_id = data.get("id", "")
            branch = data.get("branch")
            worktree_dir = data.get("worktree_dir")

            if not branch or not worktree_dir:
                continue

            worktree_path = Path(worktree_dir)
            if not worktree_path.exists():
                console.print(f"[yellow]Worktree not found for issue #{issue_id}[/yellow]")
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

                # Clear needs_push flag
                from agenttree.issues import update_issue_metadata
                update_issue_metadata(issue_id, needs_push=False)
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
        repo_name = f"{self.project_name}-agenttree"

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
        repo_name = f"{self.project_name}-agenttree"

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
