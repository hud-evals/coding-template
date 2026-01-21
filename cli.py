"""CLI entry points for backwards compatibility.

These scripts are exposed in pyproject.toml for command-line usage:
- hud_eval: Run the MCP server
- setup_problem: Set up a problem environment
- grade_problem: Grade a solution
"""
import asyncio
import logging
import os
from pathlib import Path

import click

from env import env
from grading import EnvironmentState, Grade
from scenarios import get_problem_spec, get_project_dir, spec_to_statement


logger = logging.getLogger(__name__)


def _setup_codebase(project_dir: str) -> None:
    """Set up the codebase for a task."""
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


async def _setup_problem(problem_id: str) -> str:
    """Set up a problem environment and return the statement."""
    spec = get_problem_spec(problem_id)
    project_dir = get_project_dir()

    logger.info("=== SETUP_PROBLEM DEBUG ===")
    logger.info("Problem ID: %s", problem_id)
    logger.info("Spec: %s", spec)

    logger.info("=== Starting setup_problem for %s ===", problem_id)
    _setup_codebase(project_dir)

    return spec_to_statement(spec)


async def _grade_problem(problem_id: str) -> Grade:
    """Grade a problem solution."""
    spec = get_problem_spec(problem_id)
    state = EnvironmentState()

    if spec.solution_fn is None:
        raise ValueError(f"Problem {problem_id} missing grading function")

    return spec.solution_fn(state)


@click.command()
@click.argument("problem_id")
def setup_problem_script(problem_id: str) -> None:
    """Set up a problem environment and return the problem statement."""
    statement = asyncio.run(_setup_problem(problem_id))
    print(statement)


@click.command()
@click.argument("problem_id", envvar="PROBLEM_ID")
@click.option("--only-server", is_flag=True, help="Only start the server and wait for it to be ready")
@click.option("--output_path", default="/tmp/grade_junit.xml", help="Path to output the JUNIT XML file")
def grade_problem_script(
    problem_id: str,
    only_server: bool = False,
    output_path: str = "/tmp/grade_junit.xml",
) -> None:
    """Grade a problem solution and return the grade results."""
    grade = asyncio.run(_grade_problem(problem_id))
    if grade.metadata:
        for _, grader_data in grade.metadata.items():
            if isinstance(grader_data, dict) and "junit" in grader_data:
                with open(output_path, "w") as f:
                    f.write(grader_data["junit"])
                break
    print(grade)


@click.command()
def main() -> None:
    """Run the MCP server."""
    env.run(transport="stdio")


if __name__ == "__main__":
    main()
