"""Scenarios and shared helpers for the coding environment.

This file contains:
- Shared helper functions (used by scenarios and CLI)
- Scenario definitions that directly call internal functions from env.py
"""

import json
import os

import tasks  # noqa: F401 - registers problems
from grading import PROBLEM_REGISTRY, ProblemSpec

# ============================================================================
# Shared Helpers (used by scenarios and CLI)
# ============================================================================


def get_problem_spec(problem_id: str) -> ProblemSpec:
    """Look up a problem spec by ID."""
    for spec in PROBLEM_REGISTRY:
        if spec.id == problem_id:
            return spec
    raise ValueError(f"No problem found for id: {problem_id}")


def spec_to_statement(spec: ProblemSpec, hints_enabled: bool = False) -> str:
    """Convert a problem spec to a prompt statement."""
    statement = spec.description

    if hints_enabled and len(spec.hints) > 0:
        hint_text = ""
        for hint_spec in spec.hints:
            hint_text += f"\n - {hint_spec.text}\n"
        statement += "\n\n" + f"<HINTS>{hint_text}</HINTS>"

    # [CUSTOMIZE] Update this template for your project
    template = f"""
You will be working on a task for {os.environ.get('FOLDER_NAME')}.
The repository has already been cloned in the environment in /home/ubuntu/{os.environ.get('FOLDER_NAME')}.

[Add any project-specific instructions here, for example:
- How to run tests
- Build system guidelines
- File naming conventions
- Code style requirements]

Use the tools provided to complete the following task:

<STATEMENT>
"""
    return template.replace("<STATEMENT>", statement)


def get_project_dir() -> str:
    """Get the project directory from environment or default."""
    return os.getenv("PROJECT_DIR", f"/home/ubuntu/{os.environ.get('FOLDER_NAME')}")


# ============================================================================
# Scenario Registration
# ============================================================================


def register_scenarios(env) -> None:
    """Register all scenarios on the environment."""

    @env.scenario("solve-task")
    async def solve_task(problem_id: str, hints_enabled: bool = False):
        """Solve a coding task from the problem registry.

        Args:
            problem_id: ID of the problem to solve (from tasks/)
            hints_enabled: Whether to include hints in the prompt

        This scenario:
        1. Sets PROBLEM_ID env var for patch selection
        2. Sets up the codebase
        3. Yields prompt to agent
        4. Grades solution after agent finishes
        """
        # Set PROBLEM_ID env var so grading runner can find the correct patches
        os.environ["PROBLEM_ID"] = problem_id

        # Yield prompt to agent
        prompt_result = await env.call_tool("setup_problem", problem_id=problem_id)
        # Extract text from MCPToolResult
        prompt = prompt_result.content[0].text if prompt_result.content else ""
        _ = yield prompt

        # Evaluate: call grading 
        grade_result = await env.call_tool("grade_problem", problem_id=problem_id)
        # Extract and parse JSON from MCPToolResult
        grade_text = grade_result.content[0].text if grade_result.content else "{}"
        result = json.loads(grade_text)
        yield result["score"]