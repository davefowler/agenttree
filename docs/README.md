# AgentTree Documentation

Welcome to the AgentTree documentation! This directory contains comprehensive guides, architecture docs, and planning materials.

## 📚 Documentation Index

### Getting Started
- [Main README](../README.md) - Quick start and overview
- [Installation Guide](../README.md#installation) - How to install
- [Roadmap](ROADMAP.md) - **Current status and future plans**

### Architecture
- [Agents Repository](architecture/agents-repository.md) - **How the documentation system works**
  - Repository structure
  - File naming conventions
  - Template system
  - Git operations
  - Integration points

### Development
- [Testing Strategy](development/testing.md) - **Test coverage and approaches**
  - Current coverage (25% → target 60-70%)
  - Module-specific strategies
  - Test organization
  - CI configuration
  - Quality guidelines

### Planning (Historical)
These documents capture the planning and research that led to Phase 2 implementation:

- [Planning Summary](planning/PLANNING-SUMMARY.md) - Overview of all decisions
- [Agent Notes Research](planning/agent-notes-research.md) - Folder structure, RFC format, templates
- [Container Strategy](planning/container-strategy.md) - Platform-specific container approach
- [GitHub CLI Integration](planning/github-cli-integration.md) - GitHub CLI strategy and security
- [Implementation Plan](planning/implementation-plan.md) - Detailed 6-phase plan

## 🗺️ Where We Are

**Current Phase:** End of Phase 2 ✅

**What's Complete:**
- ✅ Core package (config, worktree, tmux)
- ✅ Agents repository system
- ✅ Documentation management
- ✅ GitHub CLI integration
- ✅ Notes commands (show, search, archive)

**Next Phase:** Enhanced GitHub Integration
- Auto PR review
- CI monitoring
- Auto merge
- Issue sync

See [ROADMAP.md](ROADMAP.md) for full details.

## 🧪 Testing

**Current Coverage:** 25% overall (48 tests passing)

**Module Coverage:**
- config.py: 96%
- worktree.py: 88%
- agents_repo.py: 57%
- Others: 0% (in progress)

**Target:** 60-70% overall by end of Phase 3

See [development/testing.md](development/testing.md) for strategy.

## 🏗️ Architecture

### Core Components

```
agenttree/
├── cli.py              # Click-based CLI
├── config.py           # Configuration management
├── worktree.py         # Git worktree operations
├── tmux.py             # Tmux session management
├── github.py           # GitHub API integration
├── agents_repo.py      # Agents repository management
├── container.py        # Container runtime support
└── agents/
    ├── base.py         # BaseAgent interface
    ├── claude.py       # Claude Code adapter
    └── aider.py        # Aider adapter
```

### Agents Repository

Separate `{project}-agents` GitHub repository with this structure:

```
{project}-agents/
├── templates/          # Reusable templates
├── specs/              # Living documentation
├── tasks/              # Per-agent execution logs
├── rfcs/               # Design proposals
├── plans/              # Planning documents
└── knowledge/          # Accumulated learnings
```

See [architecture/agents-repository.md](architecture/agents-repository.md) for details.

## 🤝 Contributing

We welcome contributions! Here's how to get involved:

### For Developers

1. **Read the docs:**
   - [Main README](../README.md) for overview
   - [Testing Strategy](development/testing.md) for test guidelines
   - [Roadmap](ROADMAP.md) for planned features

2. **Pick a task:**
   - Check [GitHub Issues](https://github.com/agenttree/agenttree/issues)
   - Look for `good first issue` label
   - See Phase 3 features in roadmap

3. **Follow the process:**
   - Fork the repo
   - Create a feature branch
   - Write tests (see testing.md)
   - Submit a PR

### For Researchers

Have ideas for future phases?

- **Phase 4 (Remote Agents):** How should distributed agents work?
- **Phase 5 (Web Dashboard):** What should the UI look like?
- **Phase 6 (Agent Memory):** How do agents learn?

Join the discussion in [GitHub Discussions](https://github.com/agenttree/agenttree/discussions).

## 📖 Additional Resources

### External Links

- [Aider](https://github.com/paul-gauthier/aider) - AI pair programming (inspiration)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) - Anthropic's CLI
- [Git Worktrees](https://git-scm.com/docs/git-worktree) - Official docs
- [Tmux](https://github.com/tmux/tmux/wiki) - Terminal multiplexer

### Related Projects

- [Devin](https://devin.ai) - Commercial autonomous agent
- [OpenHands](https://github.com/All-Hands-AI/OpenHands) - Open-source autonomous agent
- [SWE-agent](https://github.com/princeton-nlp/SWE-agent) - Research autonomous agent

## 📝 Documentation Style Guide

When contributing documentation:

- **Use Markdown** - GitHub-flavored markdown
- **Include examples** - Show, don't just tell
- **Add diagrams** - ASCII art is fine
- **Keep it current** - Update "Last Updated" dates
- **Link related docs** - Help readers navigate

## 🔍 Quick Links

### Most Important Docs

1. **[Roadmap](ROADMAP.md)** - Where we're going
2. **[Agents Repository Architecture](architecture/agents-repository.md)** - How it works
3. **[Testing Strategy](development/testing.md)** - How to test

### For New Contributors

1. Read [Main README](../README.md)
2. Check [Roadmap](ROADMAP.md) Phase 3 features
3. Review [Testing Strategy](development/testing.md)
4. Pick an issue and start!

---

**Questions?** Open a [GitHub Discussion](https://github.com/agenttree/agenttree/discussions) or file an [issue](https://github.com/agenttree/agenttree/issues).
