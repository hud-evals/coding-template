"""Graders for evaluating agent solutions."""

import asyncio
import os
from typing import Literal

from hud.graders import Grader

from .runner import GradingRunner

# Validation modes used by tests/test_grading.py (no agent edits):
#   "baseline_fail" — invert the score so a correctly-failing baseline reads 1.0.
#   "golden_pass"   — grade the golden branch as-is (expected 1.0).
ValidateMode = Literal["baseline_fail", "golden_pass"]


class AgentPatchGrader(Grader):
    """Apply the hidden ``test.patch`` to an isolated copy of the repo, run pytest.

    Usage::

        await AgentPatchGrader.grade(
            weight=1.0,
            problem_id="my_task",
            test_files=["test_foo.py"],
        )

    Custom test command::

        await AgentPatchGrader.grade(
            weight=1.0,
            problem_id="my_task",
            test_files=["test_foo.test.ts"],
            test_command="yarn test {test_files}",
        )
    """

    name = "AgentPatchGrader"
    DEFAULT_TEST_COMMAND = "uv run pytest {test_files}"

    @classmethod
    async def compute_score(
        cls,
        test_files: list[str],
        problem_id: str | None = None,
        test_command: str | None = None,
        validate_mode: ValidateMode | None = None,
        repo_path: str | None = None,
        patches_dir: str | None = None,
        **kwargs,
    ) -> float:
        """Run the hidden tests against the current repo state.

        Args:
            test_files: Test files to run.
            problem_id: Problem ID for patches (default: ``PROBLEM_ID`` env).
            test_command: Test command with a ``{test_files}`` placeholder.
            validate_mode: ``"baseline_fail"`` inverts the score (validation);
                ``"golden_pass"`` grades as-is.
            repo_path: Repo to grade (default: ``PROJECT_DIR`` env / fallback).
            patches_dir: Where patches were generated (default: ``PATCHES_DIR`` env).

        Returns:
            ``1.0`` if the tests pass, ``0.0`` otherwise (inverted under
            ``"baseline_fail"``).
        """
        pid = problem_id or os.environ.get("PROBLEM_ID")
        if not pid:
            raise ValueError("problem_id required (or set PROBLEM_ID env)")

        runner = GradingRunner(
            problem_id=pid,
            test_command=test_command or cls.DEFAULT_TEST_COMMAND,
            test_files=test_files,
            repo_path=repo_path,
            patches_dir=patches_dir,
        )

        # runner.grade() blocks (copytree + git apply + pytest); run it off the
        # event loop so the served environment stays responsive.
        score = await asyncio.to_thread(runner.grade)

        # baseline_fail: a correct baseline *fails* the hidden tests, so invert.
        if validate_mode == "baseline_fail":
            score = 1.0 if score == 0.0 else 0.0

        return score
