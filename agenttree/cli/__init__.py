"""CLI for AgentTree.

This package contains the CLI commands organized into submodules:
- agents: Agent management (start, stop, attach, send, output, sandbox)
- issues: Issue management (create, list, show, doc)
- workflow: Workflow commands (status, next, approve, defer, shutdown, rollback)
- notes: Notes management (show, search, archive)
- server: Server commands (run, stop-all)
- remote: Remote agent management (list, start)
- setup: Setup commands (init, upgrade, setup, preflight)
- dev: Development commands (test, lint, sync)
- hooks: Hook management (check)
- misc: Miscellaneous commands (auto-merge, context-init, tui, cleanup)
"""

# Main CLI group from _legacy.py
from agenttree.cli._legacy import main

# Import command groups and commands from submodules
from agenttree.cli.notes import notes
from agenttree.cli.remote import remote
from agenttree.cli.cli_hooks import hooks_group
from agenttree.cli.dev import test, lint, sync_command
from agenttree.cli.misc import auto_merge, context_init, cleanup_command, tui_command
from agenttree.cli.server import run, stop_all, stalls
from agenttree.cli.issues import issue
from agenttree.cli.setup import init, upgrade, setup as setup_cmd, preflight, migrate_docs
from agenttree.cli.workflow import (
    stage_status,
    stage_next,
    approve_issue,
    defer_issue,
    shutdown_issue,
    rollback_issue,
)
from agenttree.cli.agents import (
    start_agent,
    agents_status,
    sandbox,
    attach,
    output,
    send,
    stop,
)

# Register all commands with main group
main.add_command(start_agent)
main.add_command(agents_status)
main.add_command(sandbox)
main.add_command(attach)
main.add_command(output)
main.add_command(send)
main.add_command(stop)
main.add_command(issue)
main.add_command(init)
main.add_command(upgrade)
main.add_command(setup_cmd)
main.add_command(preflight)
main.add_command(migrate_docs)
main.add_command(notes)
main.add_command(remote)
main.add_command(hooks_group)
main.add_command(test)
main.add_command(lint)
main.add_command(sync_command)
main.add_command(auto_merge)
main.add_command(context_init)
main.add_command(cleanup_command)
main.add_command(tui_command)
main.add_command(run)
main.add_command(stop_all)
main.add_command(stalls)
main.add_command(stage_status)
main.add_command(stage_next)
main.add_command(approve_issue)
main.add_command(defer_issue)
main.add_command(shutdown_issue)
main.add_command(rollback_issue)

__all__ = ["main"]
