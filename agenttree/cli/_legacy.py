"""CLI for AgentTree - main group and document commands.

This module contains the core CLI group and document creation commands
that haven't been moved to submodules yet. Over time, these will be
migrated to appropriate submodules.
"""

import click

from agenttree.cli_docs import create_rfc, create_investigation, create_note, complete, resume


@click.group()
@click.version_option(version="0.1.0")
def main() -> None:
    """AgentTree: Multi-Agent Development Framework

    Orchestrate multiple AI coding agents across git worktrees.
    """
    pass


# Add document creation commands
main.add_command(create_rfc)
main.add_command(create_investigation)
main.add_command(create_note)

# Add task management commands
main.add_command(complete)
main.add_command(resume)


if __name__ == "__main__":
    main()
