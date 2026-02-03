"""CLI entry points for backwards compatibility.

These scripts are exposed in pyproject.toml for command-line usage:
- hud_eval: Run the MCP server
- setup_problem: Set up a problem environment
- grade_problem: Grade a solution
"""
import asyncio

import click

from env import env
from grading import Grade
from scenarios import get_problem_spec, spec_to_statement


async def _setup_problem(problem_id: str) -> str:
    """Set up a problem environment and return the statement."""
    spec = get_problem_spec(problem_id)
    return spec_to_statement(spec)


async def _grade_problem(problem_id: str) -> Grade:
    """Grade a problem solution."""
    spec = get_problem_spec(problem_id)

    if spec.solution_fn is None:
        raise ValueError(f"Problem {problem_id} missing grading function")

    return spec.solution_fn()


@click.command()
@click.argument("problem_id")
def setup_problem_script(problem_id: str) -> None:
    """Set up a problem environment and return the problem statement."""
    statement = asyncio.run(_setup_problem(problem_id))
    print(statement)


@click.command()
@click.argument("problem_id", envvar="PROBLEM_ID")
@click.option("--output_path", default="/tmp/grade_junit.xml", help="Path to output the JUNIT XML file")
def grade_problem_script(
    problem_id: str,
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
