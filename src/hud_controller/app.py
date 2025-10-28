import asyncio
import logging
import os

import click
from mcp.server.fastmcp import FastMCP  # type: ignore
from mcp.types import ImageContent, TextContent  # type: ignore
from pydantic import Field

import hud_controller.extractors
from hud_controller.utils import import_submodules

from .setup import setup_codebase, start_dinit
from .spec import PROBLEM_REGISTRY, EnvironmentState, Grade, ProblemSpec
from .tools.base import ToolResult
from .tools.computer import Action

logger = logging.getLogger(__name__)
ONLY_SERVER = False

# [CUSTOMIZE] Set your MCP server name
mcp = FastMCP("agent_evaluation", port=8039, log_level="DEBUG", debug=True)

TEST_MODE = os.environ.get("MCP_TESTING_MODE", "1") in ["1", "true"]

if TEST_MODE:
    # Note, these tools are only available in testing mode for the purpose of testing
    # If the enviroment performs well with these tools, it will also work with our internal
    # implementation

    from .tools.bash import BashTool
    from .tools.computer import ComputerTool
    from .tools.edit import Command, EditTool

    computer_tool = ComputerTool()
    edit_tool = EditTool()
    bash_tool = BashTool()

    @mcp.tool(
        name="str_replace_editor",
        description="Create and edit files using str_replace_editor.  Please use absolute paths for all file names.",
    )
    async def str_replace_editor(
        *,
        command: Command,
        path: str,
        file_text: str | None = None,
        view_range: list[int] | None = None,
        old_str: str | None = None,
        new_str: str | None = None,
        insert_line: int | None = None,
    ) -> ToolResult:
        """Edit or create files using string replacement operations.

        Args:
            command (Command): The edit command to perform (e.g., create, edit, view)
            path (str): Absolute path to the target file
            file_text (str | None, optional): Content to write when creating a new file. Defaults to None.
            view_range (list[int] | None, optional): Line range to view [start, end]. Defaults to None.
            old_str (str | None, optional): String to replace when editing. Defaults to None.
            new_str (str | None, optional): Replacement string when editing. Defaults to None.
            insert_line (int | None, optional): Line number for insertion. Defaults to None.

        Returns:
            ToolResult: Result of the edit operation
        """
        return await edit_tool(
            command=command,
            path=path,
            file_text=file_text,
            view_range=view_range,
            old_str=old_str,
            new_str=new_str,
            insert_line=insert_line,
        )

    @mcp.tool()
    async def computer(
        *,
        action: Action,
        text: str | None = None,
        coordinate: tuple[int, int] | None = None,
        start_coordinate: tuple[int, int] | None = None,
        duration: int | float | None = None,
        scroll_direction: str | None = None,
        scroll_amount: int | None = None,
    ) -> list[ImageContent | TextContent]:
        """Perform computer interactions like typing, clicking, and scrolling.

        Args:
            action (Action): The type of action to perform (e.g., click, type, scroll)
            text (str | None, optional): Text to type when action is type. Defaults to None.
            coordinate (tuple[int, int] | None, optional): Screen coordinates for clicking. Defaults to None.
            start_coordinate (tuple[int, int] | None, optional): Starting coordinates for drag actions. Defaults to None.
            duration (int | float | None, optional): Duration for actions like hold. Defaults to None.
            scroll_direction (str | None, optional): Direction to scroll ('up' or 'down'). Defaults to None.
            scroll_amount (int | None, optional): Amount to scroll. Defaults to None.

        Returns:
            list[ImageContent | TextContent]: List of image or text content representing the action results
        """
        return await computer_tool(
            action=action,
            text=text,
            coordinate=coordinate,
            start_coordinate=start_coordinate,
            duration=duration,
            scroll_direction=scroll_direction,  # type: ignore[arg-type]
            scroll_amount=scroll_amount,
        )  # type: ignore[return-value]

    @mcp.tool(
        name="bash",
        description="Run bash commands. If you need to restart the bash session, set restart to true.",
    )
    async def bash(*, command: str, restart: bool = False) -> ToolResult:
        return await bash_tool(
            command=command,
            restart=restart,
        )

# import all submodules
# Import all task extractor modules to ensure problems are registered
import_submodules(hud_controller.extractors)


# [CUSTOMIZE] Update this template for your project
template = """
You will be working on a task for [PROJECT_NAME].
The repository has already been cloned in the environment in /home/ubuntu/[PROJECT_NAME].

[Add any project-specific instructions here, for example:
- How to run tests
- Build system guidelines
- File naming conventions
- Code style requirements]

Use the tools provided to complete the following task:

<STATEMENT>
"""

def spec_to_statement(spec: ProblemSpec) -> str:
    """
    Convert a problem spec to a statement.
    """
    hints_enabled = os.environ.get("HINTS", "none").lower() in ["all"]
    statement = spec.description
    
    if hints_enabled and len(spec.hints) > 0:
        hint_text = ""
        for hint_spec in spec.hints:
            hint_text += f"\n - {hint_spec.text}\n"
        statement += "\n\n" + f"<HINTS>{hint_text}</HINTS>"
    return template.replace("<STATEMENT>", statement)


# helper to lookup a problem spec by id
def _get_spec(problem_id: str) -> ProblemSpec:
    for spec in PROBLEM_REGISTRY:
        if spec.id == problem_id:
            return spec
    raise ValueError(f"No problem found for id: {problem_id}")


# Implementation notes: setup_problem will only be called once per enviroment instance
@mcp.tool()
async def setup_problem(
    problem_id: str = Field(description="The id of the problem to solve"),
) -> str:
    """Starts the enviroment and returns the problem statement"""
    spec = _get_spec(problem_id)

    logger.info(f"=== SETUP_PROBLEM DEBUG ===")
    logger.info(f"Problem ID: {problem_id}")
    logger.info(f"Spec: {spec}")

    # Start the dinit services
    await start_dinit()
    logger.info(f"=== Starting setup_problem for {problem_id} ===")
    logger.info(f"spec: {spec}")
    setup_codebase(spec.base, spec.test, spec.golden)

    # create the full statement
    return spec_to_statement(spec)


@click.command()
@click.argument("problem_id")
def setup_problem_script(problem_id: str):
    """Set up a problem environment and return the problem statement."""
    statement = asyncio.run(setup_problem(problem_id))
    print(statement)


# Implementation note: grade_problem will only be called once per enviroment instance
@mcp.tool()
async def grade_problem(
    problem_id: str,
    transcript: str | int = Field(description="The entire transcript produced by the model and its tool calls"),
) -> Grade:
    """Check your solution for grading. Returns a Grade object making sure to include all components that make up the score as subscores."""

    spec = _get_spec(problem_id)
    # invoke the solution function to get a Grade
    state = EnvironmentState()
    print(f"state: {state}")
    return spec.solution_fn(state)

@click.command()
@click.argument("problem_id", envvar="PROBLEM_ID")
@click.option("--only-server", is_flag=True, help="Only start the server and wait for it to be ready")
@click.option("--output_path", default="/tmp/grade_junit.xml", help="Path to output the JUNIT XML file")
def grade_problem_script(
    problem_id: str,
    only_server: bool = False,
    output_path: str = None,
):
    """Grade a problem solution and return the grade results."""
    global ONLY_SERVER
    ONLY_SERVER = only_server
    transcript = "dummy transcript"
    grade = asyncio.run(grade_problem(problem_id, transcript))
    with open(output_path, "w") as f:
        f.write(grade.metadata["AgentPatchGrader"]["junit"])
    print(grade)


@click.command()
def main():
    # Initialize and run the server as root; you can use files and services that require root permissions
    # once init is done, the server will run as the model user to prevent it from accessing problem data
    mcp.run(transport="stdio")
