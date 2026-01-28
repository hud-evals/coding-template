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
from hud.tools.coding import GeminiEditTool, GeminiShellTool
from hud.tools.filesystem import GeminiGlobTool, GeminiListTool, GeminiReadTool, GeminiSearchTool

from grading import EnvironmentState
from scenarios import get_problem_spec, register_scenarios
from tools import (
    BashTool,
    EditTool,
    ToolError,
)

logger = logging.getLogger(__name__)

# Create the environment
env = Environment("coding")

# Initialize tools
_bash_tool: BashTool | None = None
_edit_tool: EditTool | None = None

# Gemini tools
_gemini_shell_tool: GeminiShellTool | None = None
_gemini_read_tool: GeminiReadTool | None = None
_gemini_list_tool: GeminiListTool | None = None
_gemini_glob_tool: GeminiGlobTool | None = None
_gemini_search_tool: GeminiSearchTool | None = None
_gemini_edit_tool: GeminiEditTool | None = None


def _get_project_dir() -> str:
    """Get the project directory path."""
    return os.getenv("PROJECT_DIR", f"/home/ubuntu/{os.environ.get('FOLDER_NAME', 'project')}")


@env.initialize
async def initialize() -> None:
    """Initialize the coding environment tools."""
    global _bash_tool, _edit_tool
    global _gemini_shell_tool, _gemini_read_tool, _gemini_list_tool
    global _gemini_glob_tool, _gemini_search_tool, _gemini_edit_tool

    logger.info("Initializing coding environment")
    _bash_tool = BashTool()
    _edit_tool = EditTool()

    # Initialize Gemini tools with the project directory as base_path/base_directory
    # This allows relative paths like "server/routes/api/documents.ts" to work
    project_dir = _get_project_dir()
    _gemini_shell_tool = GeminiShellTool(base_directory=project_dir)
    _gemini_read_tool = GeminiReadTool(base_path=project_dir)
    _gemini_list_tool = GeminiListTool(base_path=project_dir)
    _gemini_glob_tool = GeminiGlobTool(base_path=project_dir)
    _gemini_search_tool = GeminiSearchTool(base_path=project_dir)
    _gemini_edit_tool = GeminiEditTool(base_directory=project_dir)

    logger.info("Coding environment initialized")


@env.shutdown
async def shutdown() -> None:
    """Clean up the coding environment."""
    global _bash_tool, _edit_tool
    global _gemini_shell_tool, _gemini_read_tool, _gemini_list_tool
    global _gemini_glob_tool, _gemini_search_tool, _gemini_edit_tool

    if _bash_tool and _bash_tool._session:
        _bash_tool._session.stop()

    _bash_tool = None
    _edit_tool = None

    # Clean up Gemini tools
    _gemini_shell_tool = None
    _gemini_read_tool = None
    _gemini_list_tool = None
    _gemini_glob_tool = None
    _gemini_search_tool = None
    _gemini_edit_tool = None

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
# Gemini Tools
# ============================================================================


def _extract_text(result: list) -> str:
    """Extract text content from hud tool results."""
    texts = []
    for block in result:
        if hasattr(block, "text"):
            texts.append(block.text)
    return "\n".join(texts) if texts else ""


@env.tool()
async def gemini_shell(
    command: str,
    description: str | None = None,
    dir_path: str | None = None,
    timeout_ms: int | None = None,
) -> str:
    """Execute a shell command (Gemini-style).

    Args:
        command: The command to execute
        description: Optional description of the command
        dir_path: Working directory for the command
        timeout_ms: Execution timeout in milliseconds

    Returns:
        The command output
    """
    if _gemini_shell_tool is None:
        return "Error: Gemini shell tool not initialized"

    try:
        result = await _gemini_shell_tool(
            command=command,
            description=description,
            dir_path=dir_path,
            timeout_ms=timeout_ms,
        )
        return _extract_text(result)
    except Exception as e:
        return f"Error: {e}"


@env.tool()
async def gemini_read(
    file_path: str,
    offset: int | None = None,
    limit: int | None = None,
) -> str:
    """Read a file with optional line offset and limit (Gemini-style).

    Args:
        file_path: Path to the file to read
        offset: Starting line number (0-based)
        limit: Maximum number of lines to retrieve

    Returns:
        File content with truncation info
    """
    if _gemini_read_tool is None:
        return "Error: Gemini read tool not initialized"

    try:
        result = await _gemini_read_tool(file_path=file_path, offset=offset, limit=limit)
        return _extract_text(result)
    except Exception as e:
        return f"Error: {e}"


@env.tool()
async def gemini_list(
    dir_path: str,
    ignore: list[str] | None = None,
) -> str:
    """List directory contents with DIR prefix (Gemini-style).

    Args:
        dir_path: Target directory to enumerate
        ignore: Glob patterns for exclusion

    Returns:
        Directory listing with DIR prefix for directories
    """
    if _gemini_list_tool is None:
        return "Error: Gemini list tool not initialized"

    try:
        result = await _gemini_list_tool(dir_path=dir_path, ignore=ignore)
        return _extract_text(result)
    except Exception as e:
        return f"Error: {e}"


@env.tool()
async def gemini_glob(
    pattern: str,
    dir_path: str | None = None,
    case_sensitive: bool = True,
    respect_git_ignore: bool = True,
) -> str:
    """Find files matching a glob pattern (Gemini-style).

    Args:
        pattern: Glob pattern for file matching
        dir_path: Base directory for search (defaults to cwd)
        case_sensitive: Enable case-sensitive matching (default: True)
        respect_git_ignore: Honor .gitignore rules (default: True)

    Returns:
        List of absolute paths sorted alphabetically
    """
    if _gemini_glob_tool is None:
        return "Error: Gemini glob tool not initialized"

    try:
        result = await _gemini_glob_tool(
            pattern=pattern,
            dir_path=dir_path,
            case_sensitive=case_sensitive,
            respect_git_ignore=respect_git_ignore,
        )
        return _extract_text(result)
    except Exception as e:
        return f"Error: {e}"


@env.tool()
async def gemini_search(
    pattern: str,
    dir_path: str | None = None,
    include: str | None = None,
) -> str:
    """Search file contents using regex (Gemini-style).

    Args:
        pattern: Regular expression to match
        dir_path: Directory to search within (defaults to cwd)
        include: Glob filter for filenames (e.g., "*.ts")

    Returns:
        Matches grouped by file with line numbers
    """
    if _gemini_search_tool is None:
        return "Error: Gemini search tool not initialized"

    try:
        result = await _gemini_search_tool(
            pattern=pattern, dir_path=dir_path, include=include
        )
        return _extract_text(result)
    except Exception as e:
        return f"Error: {e}"


@env.tool()
async def gemini_edit(
    file_path: str,
    instruction: str,
    old_string: str,
    new_string: str,
    expected_replacements: int = 1,
) -> str:
    """Replace content in a file (Gemini-style).

    Args:
        file_path: Path to the target file
        instruction: Description of the edit being made
        old_string: Text to find and replace
        new_string: Replacement text
        expected_replacements: Number of expected replacements (default: 1)

    Returns:
        Success message with updated section preview
    """
    if _gemini_edit_tool is None:
        return "Error: Gemini edit tool not initialized"

    try:
        result = await _gemini_edit_tool(
            file_path=file_path,
            instruction=instruction,
            old_string=old_string,
            new_string=new_string,
            expected_replacements=expected_replacements,
        )
        return _extract_text(result)
    except Exception as e:
        return f"Error: {e}"


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
