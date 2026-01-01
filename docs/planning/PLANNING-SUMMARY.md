# Planning Summary

## Overview

This document summarizes the planning decisions for AgentTree implementation.

## Key Decisions

### 1. Agents Repository Structure

**Decision:** Use `agents/` folder (not `.agentree/`)
- Separate git repository, ignored by parent
- Created as GitHub repo: `<project-name>-agents`
- Managed automatically by AgentTree
- Requires authenticated `gh` CLI

**Rationale:**
- Keeps AI notes separate from main codebase
- Avoids git submodule complexity
- Easy to share across team
- Can be deleted without affecting main repo

### 2. GitHub CLI Integration

**Decision:** Use `gh` CLI with safety wrappers
- Require `gh` CLI installed and authenticated
- Wrap dangerous operations (no delete, force push)
- Confirmation prompts for repo creation
- Clear error messages for missing auth

**Alternatives considered:**
- Fine-grained tokens: More secure but more friction
- Direct API: More complex, redundant with gh CLI

**Why `gh` CLI:**
- Users already have it for GitHub workflows
- Simple setup (just `gh auth login`)
- Leverages existing OAuth flow
- We can wrap it for safety

### 3. Agents Repo Folder Structure

Based on research (see `docs/agent-notes-research.md`):

```
agents/
├── templates/          # Consistency templates
├── specs/              # Living documentation
│   ├── architecture/
│   ├── features/
│   └── patterns/
├── tasks/              # Task execution logs
│   └── <agent-name>/
│       └── YYYY-MM-DD-<task>.md
├── conversations/      # Agent-to-agent discussions
├── plans/              # Active plans
│   └── archive/        # Completed/obsolete
└── knowledge/          # Accumulated wisdom
    ├── gotchas.md
    ├── decisions.md
    └── onboarding.md
```

**Key principles:**
- **Living docs** (`specs/`) vs **historical logs** (`tasks/`)
- Auto-archive old tasks (90+ days)
- Extract learnings from plans into knowledge base
- Generate onboarding docs from accumulated knowledge

### 4. Container Strategy

**Decision:** Platform-specific, simple subprocess calls

| Platform | Runtime | Why |
|----------|---------|-----|
| macOS 26+ | Apple Container | Native, free, VM isolation |
| macOS <26 | Docker | Standard fallback |
| Linux | Docker (or Podman) | Native, standard |
| Windows | Docker Desktop | Standard |

**Implementation:** Direct CLI calls (no Python wrappers)
- All three runtimes have identical CLI syntax
- Simple `subprocess.run()` calls
- No dependency on `docker-py` or `podman-py`

## Research Documents

1. **`github-cli-integration.md`**
   - How to use `gh` CLI safely
   - Authentication requirements
   - Error messaging
   - Security considerations

2. **`agent-notes-research.md`**
   - Study of existing frameworks (GitHub spec-kit, etc.)
   - Proposed folder structure
   - Workflow examples
   - Auto-generated content strategy

3. **`container-strategy.md`**
   - Platform-specific runtime choices
   - Why we DON'T need wrapper libraries
   - Security isolation levels
   - Implementation details

4. **`implementation-plan.md`**
   - Detailed phase-by-phase plan
   - Code examples
   - Testing checklist
   - Timeline estimate (~9 days)

## Questions Answered

### Q1: Separate repo or submodule?
**A:** Nested git repo, gitignored by parent (no submodule complexity)

### Q2: How to authenticate with GitHub?
**A:** Use `gh` CLI (user runs `gh auth login` once)

### Q3: What structure for notes?
**A:** See `agent-notes-research.md` - comprehensive folder structure with templates, specs, tasks, knowledge

### Q4: Which container runtime?
**A:** Apple Container on macOS 26+, Docker elsewhere, simple CLI calls

### Q5: Does Podman work with Apple Container?
**A:** No - they're separate runtimes. We detect which one is available and use it.

## Next Steps

Ready to implement! See `implementation-plan.md` for detailed steps.

**Start with:**
1. Phase 1: Agents repo management
2. Phase 2: GitHub CLI wrapper
3. Phase 3: Container simplification

## Open Questions

None - all major decisions made. Ready to proceed!
