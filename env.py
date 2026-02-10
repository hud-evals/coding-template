"""Git-enabled coding environment - tools for solving programming tasks.

This environment provides tools for:
- Running bash commands in a sandboxed shell
- Editing files with view/create/edit commands

Unlike the standard coding-template, this template gives agents FULL git access.
Agents can use git log, git blame, git diff, git commit, etc.
Grading branches (test/golden) are removed at build time so agents cannot peek
at the solution.

Supports dual-mode operation:
- HUD mode (default): scenarios with yield-based setup/grading
- Taiga mode (IS_TAIGA=1): tool-based setup_problem/grade_problem

Tools prefixed with _ are internal (hidden from agent, used by scenarios).
"""

import inspect
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

from hud import Environment
from hud.types import MCPToolResult

from grading import AgentPatchGrader, ValidateMode
from tools import BashTool, EditTool, ToolError

logger = logging.getLogger(__name__)

# Platform detection
IS_TAIGA = os.environ.get("IS_TAIGA") == "1"


class CodingEnvironment(Environment):
    """Environment subclass that strips extra tool parameters.

    Taiga may send fields not in our tool function signatures. FastMCP's
    Pydantic validation rejects unknown params, which surfaces as a
    -32602 JSON-RPC error. This override strips extras before they reach
    FastMCP's validation layer.
    """

    async def _execute_tool(self, name: str, arguments: dict[str, Any]) -> MCPToolResult:
        # For local tools, strip params not in the function signature
        tool = self._tool_manager._tools.get(name)
        if tool and hasattr(tool, "fn"):
            known = set(inspect.signature(tool.fn).parameters.keys())
            extra = set(arguments.keys()) - known
            if extra:
                logger.info("Stripping unknown params from %s: %s", name, extra)
                arguments = {k: v for k, v in arguments.items() if k in known}
        return await super()._execute_tool(name, arguments)


# Create the environment
env = CodingEnvironment("coding")

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
# Task config loader (used by both HUD scenarios and Taiga tools)
# ============================================================================


def _load_task_config() -> dict:
    """Load task_config.yaml and return the tasks dict.

    Tries to load from the build-time copy first, then falls back to
    the MCP server directory.
    """
    import yaml

    for path in ["/build_scripts/task_config.yaml", "/mcp_server/task_config.yaml"]:
        if os.path.exists(path):
            with open(path) as f:
                config = yaml.safe_load(f)
            return config.get("tasks", {})
    logger.warning("task_config.yaml not found, returning empty config")
    return {}


# ============================================================================
# Taiga Mode: setup_problem / grade_problem tools
# ============================================================================

if IS_TAIGA:
    logger.info("Taiga mode enabled (IS_TAIGA=1)")

    # Load task config once at import time
    _TASK_CONFIG = _load_task_config()

    @env.tool(output_schema=None)
    async def setup_problem(
        problem_id: str,
        task_prompt: Optional[str] = None,
        rubric: Optional[Any] = None,
        system_prompt: Optional[str] = None,
        selected_folder: Optional[str] = None,
        grader_metadata: Optional[Any] = None,
        metadata: Optional[Any] = None,
        preloaded_files: Optional[Any] = None,
        output_directory: Optional[str] = None,
        domain_allowlist: Optional[Any] = None,
        enable_anthropic_api: Optional[bool] = None,
        extra_fields: Optional[Any] = None,
    ) -> str:
        """Setup the problem environment for the given task id.

        Checks out the baseline branch and returns the task prompt.
        Patches are pre-extracted at build time — no branch manipulation needed.
        """
        logger.info("[TAIGA] setup_problem called with problem_id: %s", problem_id)

        task_cfg = _TASK_CONFIG.get(problem_id)
        if not task_cfg:
            return f"Unknown problem_id: {problem_id}. Known: {list(_TASK_CONFIG.keys())}"

        checkout = task_cfg["worktree"]["checkout"]
        setup_task(task_id=problem_id, checkout=checkout)

        prompt = make_prompt(
            task_cfg.get("prompt", f"Fix the bugs in the project. Task: {problem_id}")
        )

        # Prefer Taiga-provided task_prompt if available, otherwise use ours
        return task_prompt if task_prompt else prompt

    @env.tool(output_schema=None)
    async def grade_problem(
        problem_id: str,
        transcript: str = "",
        selected_folder: Optional[str] = None,
        grader_metadata: Optional[Any] = None,
        metadata: Optional[Any] = None,
        task_prompt: Optional[str] = None,
        rubric: Optional[Any] = None,
        system_prompt: Optional[str] = None,
        preloaded_files: Optional[Any] = None,
        output_directory: Optional[str] = None,
        domain_allowlist: Optional[Any] = None,
        enable_anthropic_api: Optional[bool] = None,
        extra_fields: Optional[Any] = None,
    ) -> dict:
        """Grade the problem by running pytest on the agent's solution.

        Copies the repo (with agent's changes), applies test.patch to add
        hidden test files, then runs pytest. Returns subscores/weights
        for Taiga's grading infrastructure.
        """
        logger.info("[TAIGA] grade_problem called for %s", problem_id)

        task_cfg = _TASK_CONFIG.get(problem_id)
        if not task_cfg:
            return {
                "subscores": {"test_pass": 0.0},
                "weights": {"test_pass": 1},
                "metadata": {"error": f"Unknown problem_id: {problem_id}"},
            }

        grading_cfg = task_cfg.get("grading", {})
        test_files = grading_cfg.get("test_files", [])
        test_command = grading_cfg.get("test_command", "pytest {test_files} -v")

        # Debug: check patch state before grading
        patches_dir = os.environ.get("PATCHES_DIR", "/home/root/patches")
        task_patches = os.path.join(patches_dir, problem_id)
        for pname in ["test.patch", "golden.patch"]:
            ppath = os.path.join(task_patches, pname)
            if os.path.exists(ppath):
                logger.info("[TAIGA] %s: %d bytes", pname, os.path.getsize(ppath))
            else:
                logger.error("[TAIGA] %s: NOT FOUND at %s", pname, ppath)

        try:
            score, grade_metadata = AgentPatchGrader.compute_score(
                test_files=test_files,
                problem_id=problem_id,
                test_command=test_command,
            )
            logger.info("[TAIGA] Grading complete: score=%s", score)
        except Exception as e:
            logger.error("[TAIGA] Grading failed: %s", e, exc_info=True)
            score = 0.0
            grade_metadata = {"error": str(e)}

        return {
            "subscores": {"test_pass": score},
            "weights": {"test_pass": 1},
            "metadata": {
                "score": score,
                "grader": "AgentPatchGrader",
                **grade_metadata,
            },
        }

    logger.info("[TAIGA] Registered setup_problem and grade_problem tools")

else:
    logger.info("HUD mode (default)")


# ============================================================================
# Import and register all scenarios from tasks/
# ============================================================================

import tasks  # noqa: E402, F401 - registers scenarios
