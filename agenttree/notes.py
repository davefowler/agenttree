"""Notes and documentation management for AgentTree.

Manages a separate .agentree/ git repository for AI-generated content.
"""

import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional


class NotesManager:
    """Manages the .agentree/ nested git repository."""

    def __init__(self, project_path: Path):
        """Initialize notes manager.

        Args:
            project_path: Path to the main project repository
        """
        self.project_path = project_path
        self.agentree_path = project_path / ".agentree"

    def ensure_notes_repo(self) -> None:
        """Initialize .agentree/ as a git repo if it doesn't exist."""
        if (self.agentree_path / ".git").exists():
            return

        # Create directory structure
        self.agentree_path.mkdir(exist_ok=True)
        (self.agentree_path / "specs").mkdir(exist_ok=True)
        (self.agentree_path / "notes").mkdir(exist_ok=True)
        (self.agentree_path / "conversations").mkdir(exist_ok=True)
        (self.agentree_path / "plans").mkdir(exist_ok=True)

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=self.agentree_path, check=True)

        # Create README
        readme = self.agentree_path / "README.md"
        readme.write_text(
            f"""# AgentTree Notes for {self.project_path.name}

This directory contains AI-generated content managed by AgentTree.

## Structure

- `specs/` - Feature specifications from GitHub issues
- `notes/` - Agent learnings and observations
- `conversations/` - Agent-to-agent discussions
- `plans/` - Architecture planning documents

## Note

This is a separate git repository, ignored by the parent project.
It has its own commit history to avoid cluttering the main repo.
"""
        )

        # Create .gitignore for temp files
        gitignore = self.agentree_path / ".gitignore"
        gitignore.write_text("*.tmp\n.DS_Store\n__pycache__/\n")

        # Initial commit
        subprocess.run(["git", "add", "."], cwd=self.agentree_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initialize AgentTree notes repository"],
            cwd=self.agentree_path,
            check=True,
        )

        # Ensure parent ignores this directory
        self._ensure_parent_gitignore()

    def _ensure_parent_gitignore(self) -> None:
        """Add .agentree/ to parent repo's .gitignore."""
        gitignore_path = self.project_path / ".gitignore"

        if gitignore_path.exists():
            content = gitignore_path.read_text()
            if ".agentree/" in content:
                return

            # Add to existing .gitignore
            with open(gitignore_path, "a") as f:
                f.write("\n# AgentTree AI notes (separate git repo)\n")
                f.write(".agentree/\n")
        else:
            # Create new .gitignore
            gitignore_path.write_text("# AgentTree AI notes\n.agentree/\n")

    def add_note(
        self, agent_num: int, content: str, category: str = "notes", auto_commit: bool = True
    ) -> None:
        """Add a note from an agent.

        Args:
            agent_num: Agent number
            content: Note content
            category: Category (notes, specs, plans)
            auto_commit: Whether to auto-commit
        """
        self.ensure_notes_repo()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note_file = self.agentree_path / category / f"agent-{agent_num}.md"

        # Append to note file
        with open(note_file, "a") as f:
            f.write(f"\n## {timestamp}\n\n{content}\n")

        if auto_commit:
            self._commit(f"Agent {agent_num}: Add {category} entry")

    def add_spec_from_issue(self, issue_number: int, title: str, body: str, url: str) -> None:
        """Create a spec file from a GitHub issue.

        Args:
            issue_number: Issue number
            title: Issue title
            body: Issue body
            url: Issue URL
        """
        self.ensure_notes_repo()

        spec_file = self.agentree_path / "specs" / f"issue-{issue_number}.md"

        content = f"""# {title}

**Issue:** [#{issue_number}]({url})
**Created:** {datetime.now().strftime("%Y-%m-%d")}

## Description

{body}

## Implementation Notes

(Agent notes will appear here as work progresses)
"""

        spec_file.write_text(content)
        self._commit(f"Add spec for issue #{issue_number}")

    def add_plan(self, name: str, content: str) -> None:
        """Add an architecture plan.

        Args:
            name: Plan name (will be slugified)
            content: Plan content
        """
        self.ensure_notes_repo()

        # Slugify name
        slug = name.lower().replace(" ", "-").replace("/", "-")
        plan_file = self.agentree_path / "plans" / f"{slug}.md"

        plan_file.write_text(
            f"""# {name}

**Created:** {datetime.now().strftime("%Y-%m-%d")}

{content}
"""
        )

        self._commit(f"Add plan: {name}")

    def _commit(self, message: str) -> None:
        """Commit changes to .agentree/ repo.

        Args:
            message: Commit message
        """
        try:
            subprocess.run(["git", "add", "."], cwd=self.agentree_path, check=True)
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.agentree_path,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            # Nothing to commit or other git error - ignore
            pass

    def get_notes(self, agent_num: int) -> str:
        """Get all notes for an agent.

        Args:
            agent_num: Agent number

        Returns:
            Note content or empty string
        """
        note_file = self.agentree_path / "notes" / f"agent-{agent_num}.md"
        if note_file.exists():
            return note_file.read_text()
        return ""

    def search_notes(self, query: str) -> list[tuple[Path, list[str]]]:
        """Search all notes for a query.

        Args:
            query: Search query

        Returns:
            List of (file_path, matching_lines)
        """
        results = []
        query_lower = query.lower()

        for category in ["notes", "specs", "plans"]:
            category_path = self.agentree_path / category
            if not category_path.exists():
                continue

            for file_path in category_path.glob("*.md"):
                content = file_path.read_text()
                matching_lines = [
                    line.strip()
                    for line in content.split("\n")
                    if query_lower in line.lower()
                ]

                if matching_lines:
                    results.append((file_path, matching_lines))

        return results

    def setup_remote(self, remote_url: str) -> None:
        """Set up remote for .agentree/ repo.

        Args:
            remote_url: Remote repository URL
        """
        self.ensure_notes_repo()

        try:
            # Add remote
            subprocess.run(
                ["git", "remote", "add", "origin", remote_url],
                cwd=self.agentree_path,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            # Remote might already exist, try to set URL instead
            subprocess.run(
                ["git", "remote", "set-url", "origin", remote_url],
                cwd=self.agentree_path,
                check=True,
            )

        # Push to remote
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=self.agentree_path,
            check=True,
        )

    def push(self) -> None:
        """Push .agentree/ repo to remote."""
        subprocess.run(
            ["git", "push"],
            cwd=self.agentree_path,
            check=True,
        )

    def get_log(self, limit: int = 10) -> str:
        """Get git log from .agentree/ repo.

        Args:
            limit: Number of commits to show

        Returns:
            Git log output
        """
        if not (self.agentree_path / ".git").exists():
            return "No notes repository initialized yet."

        result = subprocess.run(
            ["git", "log", f"-{limit}", "--oneline", "--decorate"],
            cwd=self.agentree_path,
            capture_output=True,
            text=True,
        )

        return result.stdout
