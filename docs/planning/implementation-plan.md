# AgentTree Implementation Plan

Based on planning discussions and research.

## Overview Changes

### 1. Notes Structure: `agents/` Folder (Not `.agentree/`)

**Location:** `<project>/agents/` (separate git repo, gitignored by parent)

**Key changes from current implementation:**
- ✅ Folder named `agents/` not `.agentree/`
- ✅ Separate GitHub repo: `<project-name>-agents`
- ✅ Auto-created and managed by AgentTree
- ✅ Added to parent `.gitignore`
- ✅ Requires authenticated `gh` CLI

### 2. GitHub CLI Integration

**Requirements:**
- `gh` CLI must be installed
- User must be authenticated (`gh auth status`)
- AgentTree creates `<project>-agents` repo automatically
- Wrapped operations for safety

### 3. Container Strategy

**Platform-specific:**
- macOS: Apple Container (native on macOS 26+)
- Linux: Docker (with Podman fallback)
- Windows: Docker Desktop

**Implementation:** Simple subprocess calls (no Python wrappers)

## Detailed Implementation

### Phase 1: Agents Repo Management

#### 1.1 Update `notes.py` → `agents_repo.py`

```python
# agenttree/agents_repo.py

class AgentsRepository:
    """Manages the agents/ git repository."""

    def __init__(self, project_path: Path):
        self.project_path = project_path
        self.agents_path = project_path / "agents"
        self.project_name = project_path.name

    def ensure_repo(self) -> None:
        """Ensure agents/ repo exists, create if needed."""

        # Check if agents/.git exists
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
                "Install:\n"
                "  macOS:   brew install gh\n"
                "  Linux:   See https://github.com/cli/cli#installation\n"
                "  Windows: See https://github.com/cli/cli#installation\n"
            )

        # Check auth status
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True
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
        repo_name = f"{self.project_name}-agents"

        # Check if repo already exists
        result = subprocess.run(
            ["gh", "repo", "view", repo_name],
            capture_output=True,
            text=True
        )

        if result.returncode == 0:
            # Repo exists
            return

        # Create new private repo
        subprocess.run(
            [
                "gh", "repo", "create", repo_name,
                "--private",
                "--description", f"AI agent notes for {self.project_name}",
            ],
            check=True
        )

    def _clone_repo(self) -> None:
        """Clone agents repo locally."""
        repo_name = f"{self.project_name}-agents"

        # Get current GitHub user
        result = subprocess.run(
            ["gh", "api", "user", "-q", ".login"],
            capture_output=True,
            text=True,
            check=True
        )
        username = result.stdout.strip()

        # Clone
        subprocess.run(
            [
                "gh", "repo", "clone",
                f"{username}/{repo_name}",
                str(self.agents_path)
            ],
            check=True
        )

        # Initialize structure
        self._initialize_structure()

    def _initialize_structure(self) -> None:
        """Create initial folder structure."""

        # Create directories
        (self.agents_path / "templates").mkdir(exist_ok=True)
        (self.agents_path / "specs" / "architecture").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "specs" / "features").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "specs" / "patterns").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "tasks").mkdir(exist_ok=True)
        (self.agents_path / "conversations").mkdir(exist_ok=True)
        (self.agents_path / "plans").mkdir(exist_ok=True)
        (self.agents_path / "plans" / "archive").mkdir(parents=True, exist_ok=True)
        (self.agents_path / "knowledge").mkdir(exist_ok=True)

        # Create README
        self._create_readme()

        # Create templates
        self._create_templates()

        # Create initial knowledge files
        self._create_knowledge_files()

        # Commit
        subprocess.run(["git", "add", "."], cwd=self.agents_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initialize agents repository"],
            cwd=self.agents_path,
            check=True
        )
        subprocess.run(["git", "push"], cwd=self.agents_path, check=True)

    def _add_to_gitignore(self) -> None:
        """Add agents/ to parent .gitignore."""
        gitignore = self.project_path / ".gitignore"

        if gitignore.exists():
            content = gitignore.read_text()
            if "agents/" in content:
                return

            with open(gitignore, "a") as f:
                f.write("\n# AgentTree AI notes (separate git repo)\n")
                f.write("agents/\n")
        else:
            gitignore.write_text("# AgentTree AI notes\nagents/\n")
```

#### 1.2 Folder Structure Creation

Based on `docs/agent-notes-research.md`, create:
- `/templates/` - Feature spec, task log, investigation, RFC
- `/specs/` - Architecture, features, patterns
- `/tasks/<agent-name>/` - YYYY-MM-DD-slug.md
- `/conversations/` - Agent discussions
- `/plans/` - Active plans, `/archive/` for old ones
- `/knowledge/` - gotchas.md, decisions.md, onboarding.md

#### 1.3 Auto-Generated Content

**README.md:**
- Recent activity
- Active plans
- Quick links

**specs/README.md:**
- Index of all specs
- Last updated dates

**knowledge/onboarding.md:**
- Generated from specs and knowledge
- Quick start for new agents/humans

### Phase 2: GitHub CLI Wrapper

#### 2.1 Create `github_client.py`

```python
# agenttree/github_client.py

class GitHubClient:
    """Safe wrapper around gh CLI."""

    def __init__(self, dangerous_mode: bool = False):
        self.dangerous_mode = dangerous_mode

    def create_repo(self, name: str, private: bool = True) -> None:
        """Create a repository."""
        # Validate name
        if not name.endswith("-agents"):
            raise ValueError("Agent repos must end with '-agents'")

        # Confirm in non-dangerous mode
        if not self.dangerous_mode:
            if not click.confirm(f"Create GitHub repo '{name}'?"):
                raise click.Abort()

        subprocess.run(
            ["gh", "repo", "create", name, "--private"],
            check=True
        )

    def delete_repo(self, name: str) -> None:
        """BLOCKED: Cannot delete repos."""
        raise PermissionError(
            "AgentTree cannot delete repositories for safety.\n"
            "Delete manually: gh repo delete <name>"
        )

    def get_issue(self, number: int):
        """Get issue (safe operation)."""
        # Current implementation already safe
        pass

    # ... other safe operations
```

### Phase 3: Container Support

#### 3.1 Simplify `container.py`

Based on `docs/container-strategy.md`:
- Remove complex runtime detection
- Use simple subprocess calls
- Support: container (macOS), docker (Linux/Windows), podman (Linux)

```python
# agenttree/container.py (simplified)

class ContainerRuntime:
    def _detect(self) -> Optional[str]:
        system = platform.system()

        if system == "Darwin":
            if shutil.which("container"):
                return "container"  # macOS 26+
            elif shutil.which("docker"):
                return "docker"

        elif system in ("Linux", "Windows"):
            if shutil.which("docker"):
                return "docker"
            elif shutil.which("podman"):
                return "podman"

        return None

    def run(self, image, command, worktree, **kwargs):
        """Run container - same CLI for all runtimes."""
        cmd = [
            self.runtime, "run", "-it", "--rm",
            "-v", f"{worktree}:/workspace",
            "-w", "/workspace",
            image
        ] + command

        return subprocess.run(cmd)
```

### Phase 4: CLI Updates

#### 4.1 Update `init` Command

```bash
agenttree init

# Checks:
# 1. gh CLI installed and authenticated
# 2. Creates .agenttree.yaml
# 3. Creates agents/ GitHub repo
# 4. Clones it locally
# 5. Initializes structure
# 6. Adds to .gitignore
```

#### 4.2 Update `dispatch` Command

```bash
agenttree dispatch 1 42

# New behavior:
# 1. Fetches issue #42
# 2. Creates TASK.md in worktree
# 3. Creates agents/specs/issue-42.md (spec)
# 4. Creates agents/tasks/agent-1/YYYY-MM-DD-issue-42.md (task log)
# 5. Starts agent
```

#### 4.3 Add `notes` Command Group

```bash
agenttree notes recent                    # Recent activity
agenttree notes search "auth"             # Search all notes
agenttree notes show agent-1              # Show agent's tasks
agenttree notes spec features/auth        # View spec
agenttree notes update-index              # Update README indices
agenttree notes archive --days 90         # Archive old tasks
```

### Phase 5: Task Logging

#### 5.1 Auto-Create Task Logs

When agent starts:
```markdown
# agents/tasks/agent-1/2025-01-15-fix-login-bug.md

# Task: Fix Login Bug

**Date:** 2025-01-15
**Agent:** agent-1
**Issue:** #42
**Status:** 🔄 In Progress

## Context

[Auto-populated from issue]

## Work Log

### 2025-01-15 14:30

Started investigation...

[Agent updates this as they work]
```

#### 5.2 Auto-Update on Completion

When PR created:
```markdown
## Status: ✅ Completed

## Summary

Fixed race condition in session store.

## Files Changed

- auth/session.go
- auth/session_test.go

## PR

#123

## Learnings

- Session store not thread-safe by default
- Added to knowledge/gotchas.md
```

### Phase 6: Archival System

#### 6.1 Auto-Archive Old Tasks

Monthly cron or manual:
```bash
agenttree notes archive --days 90

# Moves:
# tasks/agent-1/2024-10-15-*.md
# → tasks/archive/2024-10/agent-1-*.md
```

#### 6.2 Archive Completed Plans

```bash
# When plan completed:
# 1. Extract decisions → knowledge/decisions.md
# 2. Update specs with outcomes
# 3. Move plan → plans/archive/YYYY-MM/
```

## Migration Plan

### From Current Implementation

1. Rename `.agentree/` → `agents/`
2. Update all references in code
3. Update CLI commands
4. Update documentation

### Backward Compatibility

Not needed - this is v0.1.0, breaking changes OK.

## Testing Checklist

- [ ] `agenttree init` creates agents repo on GitHub
- [ ] `agenttree init` clones it locally
- [ ] `agenttree init` adds to .gitignore
- [ ] `agenttree dispatch` creates spec in agents/specs/
- [ ] `agenttree dispatch` creates task log
- [ ] Task log auto-updates with agent progress
- [ ] `agenttree notes search` works across all files
- [ ] Archival moves old tasks correctly
- [ ] Container mode works on macOS (Apple Container)
- [ ] Container mode works on Linux (Docker)
- [ ] Container mode works on Windows (Docker Desktop)
- [ ] gh CLI error messages are helpful
- [ ] Works when agents/ already exists
- [ ] Works when GitHub repo already exists

## Documentation Updates

- [ ] Update README.md with new structure
- [ ] Add "Getting Started" guide
- [ ] Document agents/ folder structure
- [ ] Document GitHub CLI requirements
- [ ] Add examples of task logs, specs
- [ ] Document archival strategy
- [ ] Add troubleshooting guide

## Timeline Estimate

**Phase 1:** Agents repo management - 2 days
**Phase 2:** GitHub CLI wrapper - 1 day
**Phase 3:** Container simplification - 1 day
**Phase 4:** CLI updates - 2 days
**Phase 5:** Task logging - 2 days
**Phase 6:** Archival system - 1 day

**Total:** ~9 days of focused work

## Next Steps

1. Review this plan
2. Clarify any questions
3. Begin implementation with Phase 1
4. Iterate and test as we go
