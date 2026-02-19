# AgentTree Development Commands
# Run `just` to see available commands

# Default recipe - show help
default:
    @just --list

# ============================================================================
# Development
# ============================================================================

# Run AgentTree (starts agents + web dashboard)
serve:
    uv run agenttree run

# Start the controller in tmux
controller:
    uv run agenttree controller-start

# Stop the controller
controller-stop:
    uv run agenttree controller-stop

# ============================================================================
# Testing
# ============================================================================

# Run all tests
test:
    uv run pytest

# Run unit tests only
test-unit:
    uv run pytest tests/unit

# Run integration tests only
test-integration:
    uv run pytest tests/integration

# Run tests with verbose output
test-v:
    uv run pytest -v

# Run a specific test file
test-file file:
    uv run pytest {{file}} -v

# ============================================================================
# Code Quality
# ============================================================================

# Run type checker
mypy:
    uv run mypy agenttree

# Run all checks (tests + mypy)
check: test mypy

# Run preflight checks
preflight:
    uv run agenttree preflight

# ============================================================================
# Dependencies
# ============================================================================

# Sync dependencies
sync:
    uv sync

# Update dependencies
update:
    uv sync --upgrade

# ============================================================================
# Agents
# ============================================================================

# List all agents
agents:
    uv run agenttree agents

# List all issues
issues:
    uv run agenttree issue list

# Start an agent for an issue
start issue:
    uv run agenttree start {{issue}}

# Attach to an agent's tmux session
attach issue:
    uv run agenttree attach {{issue}}

# Send a message to an agent
send issue message:
    uv run agenttree send {{issue}} "{{message}}"

# Kill an agent
kill issue:
    uv run agenttree kill {{issue}}

# ============================================================================
# Container
# ============================================================================

# Start the container runtime (Apple Containers on macOS)
container-start:
    container system start

# Check container status
container-status:
    container list

# ============================================================================
# Git / Workflow
# ============================================================================

# Show git status
status:
    git status

# Create a new issue
issue-create title problem:
    uv run agenttree issue create "{{title}}" --problem "{{problem}}"

# Approve an issue at review stage
approve issue:
    uv run agenttree approve {{issue}}

# ============================================================================
# Cleanup
# ============================================================================

# Clean Python cache files
clean:
    find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true

# ============================================================================
# Setup
# ============================================================================

# Initial project setup
setup:
    uv sync
    uv run agenttree preflight
