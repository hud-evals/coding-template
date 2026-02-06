"""CLI entry points.

These scripts are exposed in pyproject.toml for command-line usage:
- hud_eval: Run the MCP server
"""

import click

from env import env


@click.command()
def main() -> None:
    """Run the MCP server."""
    env.run(transport="stdio")


if __name__ == "__main__":
    main()
