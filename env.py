"""Coding environment - tools for solving programming tasks.

This environment provides tools for:
- Running bash commands in a sandboxed shell
- Editing files with view/create/edit commands
- Interacting with the desktop via mouse/keyboard (VNC)

Tools prefixed with _ are internal (hidden from agent, used by scenarios).
Scenarios are defined in scenarios.py and registered at the bottom of this file.
"""
import logging
import os
from pathlib import Path
from typing import Any

from hud import Environment

from grading import EnvironmentState
from scenarios import get_problem_spec, register_scenarios
from tools import BashTool, EditTool, ToolError

logger = logging.getLogger(__name__)

# Create the environment
env = Environment("coding")

# Initialize tools
_bash_tool: BashTool | None = None
_edit_tool: EditTool | None = None


@env.initialize
async def initialize() -> None:
    """Initialize the coding environment tools."""
    global _bash_tool, _edit_tool

    logger.info("Initializing coding environment")
    _bash_tool = BashTool()
    _edit_tool = EditTool()

    logger.info("Coding environment initialized")


@env.shutdown
async def shutdown() -> None:
    """Clean up the coding environment."""
    global _bash_tool, _edit_tool

    if _bash_tool and _bash_tool._session:
        _bash_tool._session.stop()

    _bash_tool = None
    _edit_tool = None
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
        # Combine stdout and stderr - stderr may contain warnings, not just errors
        output = result.output or ""
        if result.error:
            output = f"{output}\n{result.error}".strip() if output else result.error
        return output or result.system or ""
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


# ============================================================================
# Internal Tools (not registered and exposed to the agent, used by scenarios)
# ============================================================================


async def setup_codebase(project_dir: str) -> str:
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


async def grade_solution(problem_id: str) -> dict[str, Any]:
    """Grade the agent's solution for a problem.

    Args:
        problem_id: ID of the problem to grade

    Returns:
        Dict with 'score' (float 0-1) and 'subscores' (dict of sub-scores)

    This is an internal tool called by scenarios after agent interaction.
    """
    spec = get_problem_spec(problem_id)
    state = EnvironmentState()

    if spec.solution_fn is None:
        raise ValueError(f"Problem {problem_id} missing grading function")

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
# Setup/Grade Tools (called by HUD via setup_tool/evaluate_tool)
# ============================================================================


@env.tool(
    name="setup_problem",
    description="Set up a problem environment and return the problem statement.",
)
async def setup_problem(problem_id: str) -> str:
    """Set up the environment for a problem and return the statement.

    Args:
        problem_id: ID of the problem to set up

    Returns:
        The problem statement/prompt for the agent
    """
    import subprocess
    from scenarios import get_project_dir, spec_to_statement

    spec = get_problem_spec(problem_id)
    project_dir = get_project_dir()
    patches_dir = os.environ.get("PATCHES_DIR", "/home/root/patches")

    # Set PROBLEM_ID env var for grading
    os.environ["PROBLEM_ID"] = problem_id

    # Generate patches at runtime (MCP server runs as root, can access .git)
    # This generates test.patch and golden.patch
    problem_patches_dir = os.path.join(patches_dir, problem_id)
    os.makedirs(problem_patches_dir, exist_ok=True)

    if spec.base and spec.test:
        logger.info("Generating test.patch: %s → %s", spec.base, spec.test)
        result = subprocess.run(
            ["git", "diff", f"origin/{spec.base}", f"origin/{spec.test}"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        with open(os.path.join(problem_patches_dir, "test.patch"), "w") as f:
            f.write(result.stdout)

    if spec.base and spec.golden:
        logger.info("Generating golden.patch: %s → %s", spec.base, spec.golden)
        result = subprocess.run(
            ["git", "diff", f"origin/{spec.base}", f"origin/{spec.golden}"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        with open(os.path.join(problem_patches_dir, "golden.patch"), "w") as f:
            f.write(result.stdout)

    # Checkout the baseline branch for this problem
    # The agent (running as ubuntu) cannot access .git or checkout other branches
    if spec.base:
        logger.info("Checking out baseline branch: %s", spec.base)
        result = subprocess.run(
            ["git", "checkout", "-f", f"origin/{spec.base}"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error("Failed to checkout baseline: %s", result.stderr)
        else:
            logger.info("Checked out baseline branch: %s", spec.base)
            # Restore file ownership to ubuntu (git checkout as root creates root-owned files)
            subprocess.run(
                ["chown", "-R", "ubuntu:ubuntu", project_dir],
                capture_output=True,
            )
            # But keep .git protected
            subprocess.run(
                ["chown", "-R", "root:root", os.path.join(project_dir, ".git")],
                capture_output=True,
            )

    await setup_codebase(project_dir)

    logger.info("=== SETUP_PROBLEM: %s ===", problem_id)
    return spec_to_statement(spec)


@env.tool(
    name="grade_problem",
    description="Grade the solution for a problem. Returns score and subscores.",
)
async def grade_problem(problem_id: str, transcript: str = "") -> dict[str, Any]:
    """Grade the agent's solution for a problem.

    Args:
        problem_id: ID of the problem to grade
        transcript: The agent's transcript (unused, for compatibility)

    Returns:
        Dict with 'score' (float 0-1) and 'subscores' (dict of sub-scores)
    """
    # Ensure PROBLEM_ID is set for the grading runner
    os.environ["PROBLEM_ID"] = problem_id
    return await grade_solution(problem_id)


# ============================================================================
# Register Scenarios
# ============================================================================

register_scenarios(env)
