"""Coding environment - tools for solving programming tasks.

This environment provides tools for:
- Running bash commands in a sandboxed shell
- Editing files with view/create/edit commands
- Interacting with the desktop via mouse/keyboard (VNC)

Tools prefixed with _ are internal (hidden from agent, used by scenarios).
Scenarios are defined in scenarios.py and registered at the bottom of this file.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from hud import Environment

from grading import EnvironmentState, PROBLEM_REGISTRY, ProblemSpec
from scenarios import get_problem_spec, register_scenarios
from services import ServiceLoader, SimpleDinit
from tools import BashTool, ComputerTool, EditTool, ToolError

logger = logging.getLogger(__name__)

# Create the environment
env = Environment("coding")

# Initialize tools
_bash_tool: BashTool | None = None
_edit_tool: EditTool | None = None
_computer_tool: ComputerTool | None = None


@env.initialize
async def initialize() -> None:
    """Initialize the coding environment tools."""
    global _bash_tool, _edit_tool, _computer_tool

    logger.info("Initializing coding environment")
    _bash_tool = BashTool()
    _edit_tool = EditTool()
    try:
        _computer_tool = ComputerTool()
    except AssertionError:
        # ComputerTool requires WIDTH/HEIGHT env vars - skip if not available
        logger.warning("ComputerTool not available (WIDTH/HEIGHT not set)")
        _computer_tool = None

    logger.info("Coding environment initialized")


@env.shutdown
async def shutdown() -> None:
    """Clean up the coding environment."""
    global _bash_tool, _edit_tool, _computer_tool

    if _bash_tool and _bash_tool._session:
        _bash_tool._session.stop()

    _bash_tool = None
    _edit_tool = None
    _computer_tool = None
    logger.info("Coding environment shut down")


# ============================================================================
# Agent-Visible Tools
# ============================================================================


@env.tool()
async def bash(
    command: str | None = None,
    restart: bool = False,
) -> str:
    """Run a bash command in the sandboxed shell.

    Args:
        command: The bash command to execute
        restart: Whether to restart the bash session

    Returns:
        The command output or error message
    """
    if _bash_tool is None:
        return "Error: Bash tool not initialized"

    try:
        result = await _bash_tool(command=command, restart=restart)
        if result.error:
            return f"Error: {result.error}"
        return result.output or result.system or ""
    except ToolError as e:
        return f"Error: {e.message}"


@env.tool()
async def editor(
    command: str,
    path: str,
    file_text: str | None = None,
    view_range: list[int] | None = None,
    old_str: str | None = None,
    new_str: str | None = None,
    insert_line: int | None = None,
) -> str:
    """Edit files with view, create, edit, and undo operations.

    Args:
        command: One of 'view', 'create', 'str_replace', 'insert', 'undo_edit'
        path: Absolute path to the file
        file_text: Content for 'create' command
        view_range: [start_line, end_line] for 'view' command
        old_str: String to replace for 'str_replace' command
        new_str: Replacement string for 'str_replace' or 'insert'
        insert_line: Line number for 'insert' command

    Returns:
        The command result or file content
    """
    if _edit_tool is None:
        return "Error: Editor tool not initialized"

    try:
        result = await _edit_tool(
            command=command,  # type: ignore
            path=path,
            file_text=file_text,
            view_range=view_range,
            old_str=old_str,
            new_str=new_str,
            insert_line=insert_line,
        )
        if result.error:
            return f"Error: {result.error}"
        return result.output or ""
    except ToolError as e:
        return f"Error: {e.message}"


@env.tool()
async def computer(
    action: str,
    text: str | None = None,
    coordinate: list[int] | None = None,
    start_coordinate: list[int] | None = None,
    scroll_direction: str | None = None,
    scroll_amount: int | None = None,
    duration: float | None = None,
) -> list[dict[str, Any]]:
    """Interact with the desktop via mouse and keyboard.

    Args:
        action: One of 'key', 'type', 'mouse_move', 'left_click', 'right_click',
               'double_click', 'triple_click', 'middle_click', 'scroll',
               'screenshot', 'cursor_position', 'left_click_drag', etc.
        text: Text to type or key to press
        coordinate: [x, y] coordinates for mouse actions
        start_coordinate: [x, y] start position for drag actions
        scroll_direction: 'up', 'down', 'left', or 'right' for scroll
        scroll_amount: Number of scroll units
        duration: Duration for 'hold_key' or 'wait' actions

    Returns:
        List of content blocks (text and/or images)
    """
    if _computer_tool is None:
        return [{"type": "text", "text": "Error: Computer tool not available"}]

    try:
        # Convert coordinate lists to tuples if provided
        coord_tuple = tuple(coordinate) if coordinate else None
        start_coord_tuple = tuple(start_coordinate) if start_coordinate else None

        result = await _computer_tool(
            action=action,  # type: ignore
            text=text,
            coordinate=coord_tuple,  # type: ignore
            start_coordinate=start_coord_tuple,  # type: ignore
            scroll_direction=scroll_direction,  # type: ignore
            scroll_amount=scroll_amount,
            duration=duration,
        )

        # Convert MCP content blocks to dicts
        output = []
        for block in result:
            if hasattr(block, "text"):
                output.append({"type": "text", "text": block.text})
            elif hasattr(block, "data"):
                output.append({
                    "type": "image",
                    "data": block.data,
                    "mimeType": getattr(block, "mimeType", "image/png"),
                })
        return output

    except Exception as e:
        return [{"type": "text", "text": f"Error: {e}"}]


# ============================================================================
# Internal Tools (hidden from agent, used by scenarios via call_tool)
# ============================================================================


@env.tool()
async def _start_services() -> str:
    """Start all dinit services (postgres, redis, VNC, xfce4).

    This is an internal tool called by scenarios before agent interaction.
    """
    logger.info("Starting dinit services")
    loader = ServiceLoader(Path("/etc/dinit.d"))
    services = loader.load_all()
    engine = SimpleDinit(services)
    engine.start("boot")
    
    # Wait for XFCE to fully start
    test_mode = os.environ.get("MCP_TESTING_MODE", "1") in ["1", "true"]
    delay = 5 if test_mode else 30
    logger.info("Waiting %d seconds for XFCE...", delay)
    await asyncio.sleep(delay)
    
    return "Services started successfully"


@env.tool()
async def _setup_codebase(project_dir: str) -> str:
    """Set up the codebase for a coding task.

    Args:
        project_dir: Path to the project directory

    This is an internal tool called by scenarios to prepare the environment.
    """
    os.chdir(project_dir)
    
    # [OPTIONAL] Remove problematic lines from Makefile
    makefile_path = Path(project_dir) / "Makefile"
    if makefile_path.is_file():
        pattern_to_remove = "docker compose"
        with open(makefile_path, encoding="utf-8") as f:
            original_lines = f.readlines()
            filtered_lines = [
                line for line in original_lines if pattern_to_remove not in line
            ]
            if filtered_lines != original_lines:
                with open(makefile_path, "w", encoding="utf-8") as f:
                    f.writelines(filtered_lines)
                logger.info(
                    "Removed %d '%s' lines from Makefile",
                    len(original_lines) - len(filtered_lines),
                    pattern_to_remove,
                )
    
    return f"Codebase set up at {project_dir}"


@env.tool()
async def _grade_solution(problem_id: str) -> dict[str, Any]:
    """Grade the agent's solution for a problem.

    Args:
        problem_id: ID of the problem to grade

    Returns:
        Dict with 'score' (float 0-1) and 'subscores' (dict of sub-scores)

    This is an internal tool called by scenarios after agent interaction.
    """
    spec = get_problem_spec(problem_id)
    state = EnvironmentState()
    grade = spec.solution_fn(state)
    
    logger.info(
        "Grading complete: score=%.2f, subscores=%s",
        grade.score,
        grade.subscores,
    )
    
    return {
        "score": grade.score,
        "subscores": grade.subscores,
    }


# ============================================================================
# Register Scenarios
# ============================================================================

register_scenarios(env)
