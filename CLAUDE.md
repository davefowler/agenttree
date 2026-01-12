# AgentTree - Claude Instructions

## CRITICAL: Follow the Workflow

**You MUST follow the staged workflow. You cannot skip stages.**

### First: Check Your Stage
```bash
agenttree status --issue <ID>
```

Your work depends on your current stage. Don't start coding if you're at `backlog` or `problem`.

### Progress with `agenttree next`
```bash
agenttree next --issue <ID>
```

**This command handles everything automatically:**
- Commits your changes
- Pushes to the branch
- Creates PRs when needed
- Moves to the next stage

**DO NOT manually run:** `git push`, `git commit`, or `gh pr create`. The workflow handles this.

## Stages (Must Follow In Order)

| Stage | What You Do | What Happens on `next` |
|-------|-------------|------------------------|
| **backlog** | Nothing yet | → problem |
| **problem** | Write problem.md | → problem_review (waits for human) |
| **problem_review** | Wait | Human approves → research |
| **research** | Write plan.md | → plan_review (waits for human) |
| **plan_review** | Wait | Human approves → implement |
| **implement** | Write tests, then code | Auto-commits, pushes, creates PR → implementation_review |
| **implementation_review** | Wait | Human approves PR → accepted (auto-merges) |
| **accepted** | Done! | Cleanup |

## Stage Instructions

Each stage has a skill file with detailed instructions:
- `.agenttrees/skills/problem.md`
- `.agenttrees/skills/research.md`
- `.agenttrees/skills/implement.md`

**Read the skill file for your current stage before doing any work.**

## Issue Structure

Each issue has a directory: `.agenttrees/issues/<ID>-<slug>/`
- `issue.yaml` - Status, stage, metadata
- `problem.md` - Problem statement
- `plan.md` - Implementation plan (created in research stage)

## Key Files

- `.agenttree.yaml` - Project configuration
- `.agenttrees/` - Issues, skills, templates (separate git repo)
- `.worktrees/` - Agent worktrees
