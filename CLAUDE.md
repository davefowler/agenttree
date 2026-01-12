# AgentTree - Claude Instructions

## Your Workflow

You work on issues tracked in `.agenttrees/issues/`. Use these commands:

```bash
# Check your current issue and stage
agenttree status --issue <ID>

# Move to next stage/substage
agenttree next --issue <ID>

# Start a specific stage
agenttree begin <stage> --issue <ID>
```

## Issue Structure

Each issue has a directory: `.agenttrees/issues/<ID>-<slug>/`
- `issue.yaml` - Status, stage, metadata
- `problem.md` - Problem statement
- `plan.md` - Implementation plan (created in research stage)

## Stages

1. **problem** - Define the problem clearly
2. **problem_review** - Human reviews problem statement
3. **research** - Explore codebase, create plan
4. **plan_review** - Human reviews plan
5. **implement** - Write tests, then code (TDD)
6. **implementation_review** - Human reviews PR
7. **accepted** - Done!

## Stage Instructions

Each stage has a skill file with detailed instructions:
- `.agenttrees/skills/problem.md`
- `.agenttrees/skills/research.md`
- `.agenttrees/skills/implement.md`

Read the skill file when you start a stage.

## Key Files

- `.agenttree.yaml` - Project configuration
- `.agenttrees/` - Issues, skills, templates (separate git repo)
- `.worktrees/` - Agent worktrees
