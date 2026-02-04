"""CLI for AgentTree."""

import click

from agenttree.cli_docs import create_rfc, create_investigation, create_note, complete, resume


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """AgentTree: Multi-Agent Development Framework

    Orchestrate multiple AI coding agents across git worktrees.
    """
    pass


# Register commands from cli_docs (already extracted)
main.add_command(create_rfc)
main.add_command(create_investigation)
main.add_command(create_note)
main.add_command(complete)
main.add_command(resume)

# Import and register command modules
from agenttree.cli import notes
from agenttree.cli import remote
from agenttree.cli import hooks_cmd
from agenttree.cli import server
from agenttree.cli import config_cmd
from agenttree.cli import issue
from agenttree.cli import utils
from agenttree.cli import agent
from agenttree.cli import workflow
from agenttree.cli import rollback_cmd

# Notes group
main.add_command(notes.notes)

# Remote group
main.add_command(remote.remote)

# Hooks group
main.add_command(hooks_cmd.hooks_group)

# Server commands
main.add_command(server.web)
main.add_command(server.serve)
main.add_command(server.run)
main.add_command(server.stop_all)
main.add_command(server.stalls)
main.add_command(server.auto_merge)

# Config commands
main.add_command(config_cmd.init)
main.add_command(config_cmd.upgrade)
main.add_command(config_cmd.setup)
main.add_command(config_cmd.preflight)

# Issue group
main.add_command(issue.issue)

# Utils commands
main.add_command(utils.sync_command)
main.add_command(utils.cleanup_command)
main.add_command(utils.test)
main.add_command(utils.lint)
main.add_command(utils.tui_command)
main.add_command(utils.context_init)

# Agent commands
main.add_command(agent.start_agent)
main.add_command(agent.stop)
main.add_command(agent.attach)
main.add_command(agent.send)
main.add_command(agent.kill_alias)
main.add_command(agent.agents_status)
main.add_command(agent.sandbox)

# Workflow commands
main.add_command(workflow.stage_status)
main.add_command(workflow.stage_next)
main.add_command(workflow.approve_issue)
main.add_command(workflow.defer_issue)
main.add_command(workflow.shutdown_issue)

# Rollback command
main.add_command(rollback_cmd.rollback_issue)

__all__ = ["main"]
