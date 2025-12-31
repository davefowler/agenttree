# Plan: AgentTree Setup - AI-Assisted Integration

**Goal**: Make it trivially easy for users to set up AgentTree by having their existing AI agent (Cursor, Claude Code, etc.) do the integration work.

**Key Insight**: Users are already working with an AI agent when they want to set this up. Instead of building complex detection and wizard logic, we just generate clear instructions that their AI can implement.

---

## User Experience Target

```bash
# User is already in Cursor or Claude Code working on their project
cd ~/Projects/myapp
agenttree init

# Output:
# ✓ AgentTree initialization instructions copied to clipboard!
#
# Next step: Paste this into your AI agent (Cursor/Claude Code)
# Your AI will create the necessary integration scripts.
#
# Instructions also available at: https://docs.agenttree.dev/setup
```

The clipboard now contains:

```markdown
# AgentTree Integration Setup

I need you to set up AgentTree for this project. AgentTree lets me run multiple AI coding agents in parallel using git worktrees.

## What you need to create:

### 1. Create `.agenttree/setup-worktree.sh`

This script sets up a single agent worktree. It should:
- Create a git worktree at `~/Projects/worktrees/<project>-agent-N`
- Copy environment configuration (e.g., `.env`, `.env.example`)
- Set up the development environment (venv, npm install, etc.)
- Configure agent-specific settings (unique PORT if needed)

Example structure:
```bash
#!/bin/bash
AGENT_NUM=$1
WORKTREE_PATH="$HOME/Projects/worktrees/$(basename $(pwd))-agent-$AGENT_NUM"

# Create worktree
git worktree add "$WORKTREE_PATH" -b "agent-$AGENT_NUM-work"

# Setup environment (customize for this project)
cd "$WORKTREE_PATH"
# - Copy .env
# - Create venv / npm install
# - Set unique PORT=$((8000 + AGENT_NUM))
# - Any other project-specific setup
```

### 2. Create `scripts/dispatch.sh` (or update if exists)

This script dispatches a task to an agent:
- Takes agent number and task/issue as arguments
- Resets the worktree to latest main
- Creates a TASK.md file with the task description
- Starts the AI tool (claude/aider) in a tmux session
- Handles GitHub issue integration if issue number provided

### 3. Create `scripts/agents.sh` (or update if exists)

This script manages agent tmux sessions:
- List all running agents
- Attach to an agent's tmux session
- Send commands to agents
- Kill agent sessions
- Show agent status

### 4. Update `AGENTS.md` (or `.cursorrules` or similar)

Add a section explaining the AgentTree workflow so AI agents understand:
- Check for TASK.md file at startup
- Workflow for creating feature branches
- How to submit work via `./scripts/submit.sh`
- Multi-agent etiquette (don't conflict with other agents)

Example addition:
```markdown
## AgentTree Multi-Agent Setup

If you find a TASK.md file, you're in an agent worktree with an assigned task.

Workflow:
1. Read TASK.md for your assignment
2. Create feature branch: `git checkout -b issue-<number>` or `git checkout -b feature/<name>`
3. Implement the task
4. Commit with issue reference: `git commit -m "Your message (Fixes #123)"`
5. Submit: `./scripts/submit.sh` (pushes branch, creates PR, monitors CI)

Note: You're in a worktree. Other agents may be working in parallel on different tasks.
```

### 5. Create `scripts/submit.sh` (if doesn't exist)

This script handles PR creation and CI monitoring:
- Push current branch
- Create GitHub PR
- Monitor CI status
- Remove TASK.md when done

## Project-specific context:

Look at this project and customize the scripts for:
- How to set up the dev environment (Python venv? npm install? Docker?)
- Environment variables needed
- Database setup
- Port allocation (if running services)
- Testing commands
- Any special build steps

Reference implementation: https://github.com/davefowler/agenttree/blob/main/spec.md#reference-implementation-working-scripts

## After setup:

Create these files, then I'll test with:
```bash
# Setup first agent
./.agenttree/setup-worktree.sh 1

# Dispatch a test task
./scripts/dispatch.sh 1 --task "Add a hello world function"
```
```

**Time to setup: < 2 minutes** (for the AI to implement)

---

## Implementation Plan

### Phase 1: Instruction Generator (Week 1)

Simple script that generates the instructions:

```python
# agenttree/init.py

SETUP_INSTRUCTIONS = """
# AgentTree Integration Setup

I need you to set up AgentTree for this project...
[full instructions from above]
"""

def init_command():
    """Initialize AgentTree in current repo"""

    # Check if already initialized
    if Path(".agenttree").exists():
        print("✓ AgentTree already initialized")
        print("  Scripts in: .agenttree/")
        return

    # Get project name
    repo = git.Repo(".")
    project_name = Path.cwd().name

    # Generate instructions with project context
    instructions = SETUP_INSTRUCTIONS.format(
        project=project_name,
        repo_url=repo.remotes.origin.url if repo.remotes else "N/A"
    )

    # Copy to clipboard
    try:
        import pyperclip
        pyperclip.copy(instructions)
        print("✓ AgentTree setup instructions copied to clipboard!")
        print()
        print("Next step: Paste this into your AI agent (Cursor/Claude Code)")
        print("Your AI will create the necessary integration scripts.")
    except ImportError:
        print("✓ AgentTree setup instructions:")
        print()
        print(instructions)
        print()
        print("Copy the above and paste into your AI agent.")

    print()
    print("Instructions also available at:")
    print("  https://docs.agenttree.dev/setup")

    # Create marker directory
    Path(".agenttree").mkdir(exist_ok=True)
    Path(".agenttree/.gitkeep").touch()
```

**That's it!** No complex detection, no wizard, no templates. Just clear instructions.

### Phase 2: Validation Helper (Week 1)

Add a command to check if setup was done correctly:

```bash
agenttree doctor

# Output:
# AgentTree Setup Check
#
# ✓ .agenttree/ directory exists
# ✓ .agenttree/setup-worktree.sh found and executable
# ✓ scripts/dispatch.sh found and executable
# ✓ scripts/agents.sh found and executable
# ✓ scripts/submit.sh found and executable
# ✓ AGENTS.md contains AgentTree instructions
# ✓ Git worktrees supported
# ✓ tmux installed
# ✓ gh CLI installed
#
# ✓ All checks passed! Ready to use AgentTree.
#
# Try: ./scripts/dispatch.sh 1 --task "Your first task"
```

### Phase 3: Quick Start Template (Week 1)

For users who want a template to modify rather than building from scratch:

```bash
agenttree init --template

# Creates:
# .agenttree/setup-worktree.sh    (generic template)
# scripts/dispatch.sh              (generic template)
# scripts/agents.sh                (generic template)
# scripts/submit.sh                (generic template)
#
# With TODO comments showing what to customize
```

This gives users a starting point but they still need to customize for their project (or have their AI do it).

### Phase 4: Documentation Site (Week 2)

Create `docs.agenttree.dev` with:
- Setup guide (the instructions)
- Script examples for different project types
- Troubleshooting
- Best practices
- Video walkthrough

---

## What Goes in AGENTS.md?

Add a section that helps AI agents understand the AgentTree context:

```markdown
## AgentTree Multi-Agent Workflow

This project uses AgentTree for parallel agent development.

### Agent Worktree Detection

If you find a `TASK.md` file in the repository root, you are in an agent worktree with a specific task assigned.

### Workflow When TASK.md Exists

1. **Read TASK.md** - This contains your specific assignment
2. **Create branch** - Use the branch name suggested in TASK.md or create: `git checkout -b issue-<number>` or `git checkout -b feature/<descriptive-name>`
3. **Implement the task** - Follow the project's coding standards in .cursorrules
4. **Commit changes** - Include issue reference: `git commit -m "Your message (Fixes #123)"`
5. **Submit work** - Run `./scripts/submit.sh` which will:
   - Push your branch
   - Create a GitHub PR
   - Monitor CI status
   - Report any failures

### Multi-Agent Awareness

- You're in a git worktree, not the main repository
- Other agents may be working in parallel on different tasks
- Don't modify shared configuration or infrastructure without coordination
- Your changes are isolated until the PR is merged

### Environment

- This worktree has its own:
  - Virtual environment / node_modules
  - Database (if applicable)
  - PORT number (check .env)
- Changes to .env in this worktree don't affect other agents

### Submitting Work

The `./scripts/submit.sh` script handles the full PR workflow:
- Creates PR with issue reference
- Monitors CI automatically
- Alerts if CI fails so you can fix and push again
- Removes TASK.md when complete

After PR is merged, this worktree will be reset for the next task.
```

**This helps AI agents immediately understand:**
- How to detect they're in an agent worktree (TASK.md)
- What workflow to follow
- How to avoid conflicts with other agents
- Environment isolation details

---

## Implementation Complexity

| Component | Effort | LOC |
|-----------|--------|-----|
| Instruction generator | 2 hours | ~100 |
| Clipboard integration | 30 min | ~20 |
| Doctor/validation command | 3 hours | ~150 |
| Template generator | 2 hours | ~200 |
| Documentation site | 1 day | N/A |

**Total: 2-3 days of work** (vs 3 weeks for the wizard approach!)

---

## Why This Works Better

1. **Leverages existing AI**: User is already in Cursor/Claude - let it do the work
2. **Project-aware**: Their AI knows their project better than we could detect
3. **Simpler for us**: No complex detection logic, no wizard UI
4. **More flexible**: AI can adapt to weird project structures
5. **Self-documenting**: The instructions serve as documentation
6. **Faster to ship**: Days instead of weeks

---

## Alternative: Docs Link Only

Even simpler option:

```bash
agenttree init

# Output:
# ✓ AgentTree initialization started
#
# Follow the setup guide:
#   https://docs.agenttree.dev/setup
#
# Or paste this into your AI agent:
#   "Set up AgentTree for this project following: https://docs.agenttree.dev/setup"
```

The docs would have the full instructions. This is the absolute minimum viable version.

---

## Success Metrics

- ⏱️ Time from `agenttree init` to working agent: **< 5 minutes** (including AI implementation time)
- 📉 Setup failure rate: **< 10%** (AI might make mistakes, but can self-correct)
- 🎯 Works for 90%+ of projects: **Yes** (AI adapts to project)
- 😊 User doesn't need to configure anything: **Yes** (AI does it)

---

## Next Steps

1. **Week 1**: Build instruction generator + doctor command
2. **Week 1**: Create docs site with examples
3. **Week 2**: Test with 10 different project types
4. **Week 2**: Add optional template generator
5. **Week 3**: Polish and ship

The key is: **We generate instructions, the user's AI does the integration.**

Much simpler, faster to ship, and actually more robust than trying to auto-detect everything.
