# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-12-30

### Added
- Initial implementation of AgentTree multi-agent framework
- Configuration management system (.agenttree.yaml)
- Git worktree management for agent isolation
- Tmux session management for each agent
- GitHub integration (issues, PRs, CI monitoring)
- BaseAgent interface with Claude Code and Aider adapters
- Container runtime support (Docker, Podman, Apple Container)
- CLI commands: init, setup, dispatch, status, attach, send, kill
- Comprehensive test suite (34 tests, all passing)
- Full documentation and README
- Example configuration file

### Core Features
- Parallel agent execution across git worktrees
- Busy detection (TASK.md or uncommitted changes)
- Per-agent environment isolation (venv, PORT, database)
- GitHub issue dispatch and tracking
- Ad-hoc task support
- Force dispatch for overriding busy agents
- Container mode for isolated/autonomous operation

### Modules Implemented
- `agenttree.config` - Configuration management (96% test coverage)
- `agenttree.worktree` - Git worktree operations (88% test coverage)
- `agenttree.tmux` - Tmux session management
- `agenttree.github` - GitHub API integration
- `agenttree.agents.base` - Agent adapters
- `agenttree.container` - Container runtime support
- `agenttree.cli` - Command-line interface

### Development
- Test-driven development approach
- Pytest test framework with coverage reporting
- Black code formatting
- Ruff linting
- MyPy type checking
- Comprehensive type annotations
