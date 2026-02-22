"""MCP server command."""

import click


@click.command("mcp")
@click.option("--http", is_flag=True, help="Use HTTP transport (for remote/voice access)")
@click.option("--host", default="0.0.0.0", help="Host to bind to (HTTP only)")
@click.option("--port", default=8100, type=int, help="Port to bind to (HTTP only)")
def mcp_serve(http: bool, host: str, port: int) -> None:
    """Start the MCP server for external AI assistant access.

    Exposes agenttree operations (status, send, create, approve, etc.)
    as MCP tools that can be used by Claude Desktop, ChatGPT voice, or
    any MCP-compatible client.

    Examples:
        agenttree mcp                    # stdio (Claude Desktop)
        agenttree mcp --http             # HTTP on port 8100
        agenttree mcp --http --port 9100 # custom port
    """
    from agenttree.mcp_server import run_mcp_server

    if http:
        click.echo(f"Starting AgentTree MCP server (HTTP) on {host}:{port}")
        click.echo(f"MCP endpoint: http://{host}:{port}/mcp")
        click.echo("Press Ctrl+C to stop\n")
    else:
        # stdio mode — don't print to stdout (it's the MCP transport)
        import sys
        print("Starting AgentTree MCP server (stdio)", file=sys.stderr)

    run_mcp_server(http=http, host=host, port=port)
