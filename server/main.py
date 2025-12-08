import asyncio
import logging
import os

import click
import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
from pydantic import Field

import server.problems
from server.utils import import_submodules

from .spec import PROBLEM_REGISTRY, Grade, ProblemSpec

logger = logging.getLogger(__name__)

# [CUSTOMIZE] Set your MCP server name
mcp = FastMCP("agent_evaluation", port=8039, log_level="DEBUG", debug=True)

TEST_MODE = os.environ.get("MCP_TESTING_MODE", "1") in ["1", "true"]

http_client = httpx.AsyncClient(base_url="http://localhost:8000", timeout=120.0)

if TEST_MODE:
    # Note, these tools are only available in testing mode for the purpose of testing
    # If the environment performs well with these tools, it will also work with our internal
    # implementation

    @mcp.tool(
        name="str_replace_editor",
        description="Create and edit files using str_replace_editor.  Please use absolute paths for all file names.",
    )
    async def str_replace_editor(
        *,
        command: str,
        path: str,
        file_text: str | None = None,
        view_range: list[int] | None = None,
        old_str: str | None = None,
        new_str: str | None = None,
        insert_line: int | None = None,
    ) -> dict:
        """Edit or create files using string replacement operations.

        Args:
            command: The edit command to perform (e.g., create, edit, view)
            path: Absolute path to the target file
            file_text: Content to write when creating a new file
            view_range: Line range to view [start, end]
            old_str: String to replace when editing
            new_str: Replacement string when editing
            insert_line: Line number for insertion

        Returns:
            Result of the edit operation
        """
        response = await http_client.post(
            "/edit",
            json={
                "command": command,
                "path": path,
                "file_text": file_text,
                "view_range": view_range,
                "old_str": old_str,
                "new_str": new_str,
                "insert_line": insert_line,
            },
        )
        if response.status_code != 200:
            error_detail = response.json().get("detail", "Unknown error")
            return {"error": error_detail}
        data = response.json()
        return {k: v for k, v in data.items() if v is not None}

    @mcp.tool()
    async def computer(
        *,
        action: str,
        text: str | None = None,
        coordinate: tuple[int, int] | None = None,
        start_coordinate: tuple[int, int] | None = None,
        duration: int | float | None = None,
        scroll_direction: str | None = None,
        scroll_amount: int | None = None,
    ) -> list:
        """Perform computer interactions like typing, clicking, and scrolling.

        Args:
            action: The type of action to perform (e.g., click, type, scroll)
            text: Text to type when action is type
            coordinate: Screen coordinates for clicking
            start_coordinate: Starting coordinates for drag actions
            duration: Duration for actions like hold
            scroll_direction: Direction to scroll ('up' or 'down')
            scroll_amount: Amount to scroll

        Returns:
            List of image or text content representing the action results
        """
        response = await http_client.post(
            "/computer",
            json={
                "action": action,
                "text": text,
                "coordinate": coordinate,
                "start_coordinate": start_coordinate,
                "duration": duration,
                "scroll_direction": scroll_direction,
                "scroll_amount": scroll_amount,
            },
        )
        if response.status_code != 200:
            error_detail = response.json().get("detail", "Unknown error")
            return [{"type": "text", "text": f"Error: {error_detail}"}]

        # Response is list of content items
        return response.json()

    @mcp.tool(
        name="bash",
        description="Run bash commands. If you need to restart the bash session, set restart to true.",
    )
    async def bash(*, command: str, restart: bool = False) -> dict:
        response = await http_client.post(
            "/bash",
            json={"command": command, "restart": restart},
        )
        if response.status_code != 200:
            error_detail = response.json().get("detail", "Unknown error")
            return {"error": error_detail}
        data = response.json()
        return {k: v for k, v in data.items() if v is not None}

# import all submodules
# Import all task extractor modules to ensure problems are registered
import_submodules(server.problems)


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


# Implementation notes: setup_problem will only be called once per environment instance
@mcp.tool()
async def setup_problem(
    problem_id: str = Field(description="The id of the problem to solve"),
) -> str:
    """Starts the environment and returns the problem statement"""
    spec = _get_spec(problem_id)

    logger.info(f"=== SETUP_PROBLEM DEBUG ===")
    logger.info(f"Problem ID: {problem_id}")
    logger.info(f"Spec: {spec}")

    # Call environment server to start dinit
    response = await http_client.post("/setup")
    if response.status_code != 200:
        raise RuntimeError(f"Failed to setup dinit: {response.text}")

    # create the full statement
    return spec_to_statement(spec)


@click.command()
@click.argument("problem_id")
def setup_problem_script(problem_id: str):
    """Set up a problem environment and return the problem statement."""
    statement = asyncio.run(setup_problem(problem_id))
    print(statement)


# Implementation note: grade_problem will only be called once per environment instance
@mcp.tool()
async def grade_problem(
    problem_id: str,
    transcript: str | int = Field(description="The entire transcript produced by the model and its tool calls"),
) -> Grade:
    """Check your solution for grading. Returns a Grade object making sure to include all components that make up the score as subscores."""

    spec = _get_spec(problem_id)

    response = await http_client.post(
        "/grade",
        json={"base": spec.base, "test": spec.test, "golden": spec.golden, "only_server": False},
    )

    if response.status_code != 200:
        raise RuntimeError(f"Failed to grade problem: {response.text}")

    data = response.json()
    success = data["success"]
    result = data["result"]

    if success:
        logger.info("Grading successful!")
    else:
        logger.error("Grading failed!")

    grade = Grade(
        subscores={"Tests": 1.0 if success else 0.0},
        weights={"Tests": 1.0},
        metadata=result,
    )

    return grade

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
    transcript = "dummy transcript"

    # Call with only_server flag
    spec = _get_spec(problem_id)

    async def run_grade():
        response = await http_client.post(
            "/grade",
            json={"base": spec.base, "test": spec.test, "golden": spec.golden, "only_server": only_server},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Failed to grade problem: {response.text}")
        return response.json()

    data = asyncio.run(run_grade())
    success = data["success"]
    result = data["result"]

    grade = Grade(
        subscores={"Tests": 1.0 if success else 0.0},
        weights={"Tests": 1.0},
        metadata=result,
    )

    if "junit" in result:
        with open(output_path, "w") as f:
            f.write(result["junit"])

    print(grade)


@click.command()
def main():
    # Initialize and run the server as root; you can use files and services that require root permissions
    # once init is done, the server will run as the model user to prevent it from accessing problem data
    mcp.run(transport="stdio")
