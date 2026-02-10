"""Git-enabled coding environment - tools for solving programming tasks.

This environment provides tools for:
- Running bash commands in a sandboxed shell
- Editing files with view/create/edit commands

Unlike the standard coding-template, this template gives agents FULL git access.
Agents can use git log, git blame, git diff, git commit, etc.
Grading branches (test/golden) are removed at build time so agents cannot peek
at the solution.

Tools prefixed with _ are internal (hidden from agent, used by scenarios).
"""

import logging
import os
import subprocess
from pathlib import Path

from hud import Environment

from grading import ValidateMode
from tools import BashTool, EditTool, ToolError

logger = logging.getLogger(__name__)

# Create the environment
env = Environment("coding")

# Initialize tools
_bash_tool: BashTool | None = None
_edit_tool: EditTool | None = None


def _get_project_dir() -> str:
    """Get the project directory path."""
    return os.getenv("PROJECT_DIR", f"/home/ubuntu/{os.environ.get('FOLDER_NAME', 'project')}")


@env.initialize
async def initialize() -> None:
    """Initialize the coding environment tools."""
    global _bash_tool, _edit_tool

    logger.info("Initializing git-enabled coding environment")
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
# Scenario Helpers (called by @env.scenario functions in tasks/)
# ============================================================================


def setup_task(
    task_id: str,
    checkout: str,
    validate_mode: ValidateMode | None = None,
) -> None:
    """Set up environment for a task: checkout starting branch.

    In this git-enabled template, patches are pre-extracted at Docker build time.
    This function just sets the PROBLEM_ID and checks out the starting branch.
    The agent has full git access (log, blame, diff, commit, etc.).

    For golden_pass validation, the golden.patch is applied on top of the
    checkout branch so that the grading tests pass without any agent action.

    Args:
        task_id: Unique identifier for the task (matches key in task_config.yaml)
        checkout: Branch to checkout as agent starting point
        validate_mode: Set by imagectl4.py during validation (baseline_fail or golden_pass)
    """
    project_dir = _get_project_dir()
    patches_dir = os.environ.get("PATCHES_DIR", "/home/root/patches")

    # Set PROBLEM_ID env var for grading runner
    os.environ["PROBLEM_ID"] = task_id

    # Checkout the starting branch
    logger.info("Checking out branch: %s", checkout)
    result = subprocess.run(
        ["git", "checkout", "-f", checkout],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("Failed to checkout %s: %s", checkout, result.stderr)
    else:
        logger.info("Checked out branch: %s", checkout)

    # For golden_pass validation: apply the pre-built golden.patch
    # This simulates the agent having applied the correct fix
    if validate_mode == "golden_pass":
        golden_patch = os.path.join(patches_dir, task_id, "golden.patch")
        if os.path.exists(golden_patch):
            logger.info("Applying golden.patch for validation")
            with open(golden_patch) as f:
                patch_content = f.read()
            if patch_content.strip():
                result = subprocess.run(
                    ["git", "apply", "--allow-empty"],
                    cwd=project_dir,
                    input=patch_content,
                    capture_output=True,
                    text=True,
                )
                if result.returncode != 0:
                    logger.error("Failed to apply golden.patch: %s", result.stderr)
                else:
                    logger.info("Golden patch applied successfully")
            else:
                logger.info("Golden patch is empty, nothing to apply")
        else:
            logger.error("golden.patch not found at %s", golden_patch)

    # Ensure agent owns the working tree
    subprocess.run(
        ["chown", "-R", "ubuntu:ubuntu", project_dir],
        capture_output=True,
    )
    # Keep .git owned by ubuntu too (agent has full git access in this template)

    os.chdir(project_dir)


def make_prompt(description: str) -> str:
    """Generate a prompt from a task description.

    Args:
        description: The task description

    Returns:
        Formatted prompt string
    """
    folder_name = os.environ.get('FOLDER_NAME', 'project')
    return f"""You will be working on a task for {folder_name}.
The repository has already been cloned in /home/ubuntu/{folder_name}.
You have full git access — use git log, git blame, git diff, etc. to investigate.

Use the tools provided to complete the following task:

{description}
"""


# ============================================================================
# Import and register all scenarios from tasks/
# ============================================================================

import tasks  # noqa: E402, F401 - registers scenarios
