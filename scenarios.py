"""Scenarios and shared helpers for the coding environment.

This file contains:
- Shared helper functions (used by scenarios and CLI)
- Scenario definitions (use call_tool, work in both container and dev mode)

Scenarios use env.call_tool() which routes to:
- Local tool functions when running in the container
- HTTP calls when connected to a dev server
"""
import os

from grading import PROBLEM_REGISTRY, ProblemSpec
import tasks  # noqa: F401 - registers problems


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
    return template.replace("<STATEMENT>", statement)


def get_project_dir() -> str:
    """Get the project directory from environment or default."""
    return os.getenv("PROJECT_DIR", "/home/ubuntu/[PROJECT_NAME]")


# ============================================================================
# Scenario Registration
# ============================================================================


def register_scenarios(env) -> None:
    """Register all scenarios on the environment.
    
    Scenarios use env.call_tool() which automatically routes to:
    - Local tool functions (when running in container)
    - Remote tools via HTTP (when connected to dev server)
    """

    @env.scenario("solve-task")
    async def solve_task(problem_id: str, hints_enabled: bool = False):
        """Solve a coding task from the problem registry.

        Args:
            problem_id: ID of the problem to solve (from tasks/)
            hints_enabled: Whether to include hints in the prompt

        This scenario:
        1. Calls _start_services (starts postgres, redis, VNC, xfce4)
        2. Calls _setup_codebase (prepares the project)
        3. Yields prompt to agent
        4. Calls _grade_solution after agent finishes
        """
        spec = get_problem_spec(problem_id)
        project_dir = get_project_dir()

        # Setup phase: call internal tools
        await env.call_tool("_start_services")
        await env.call_tool("_setup_codebase", {"project_dir": project_dir})

        # Yield prompt to agent
        prompt = spec_to_statement(spec, hints_enabled)
        _ = yield prompt

        # Evaluate: call grading
        result = await env.call_tool("_grade_solution", {"problem_id": problem_id})
        yield result["score"]
