import glob
import os
from typing import Any, Dict, Literal, Tuple, Union

from .runner import GradingRunner
from .spec import EnvironmentState, Grader


class DefaultTestCasesPassingGrader(Grader):
    """
    A grader that checks if the all test cases are passing, within the codebase.
    """

    name = "DefaultTestCasesPassingGrader"

    @classmethod
    def compute_score(cls, state: EnvironmentState) -> float:
        """
        Compute a score based on whether the test cases are passing.
        """
        import subprocess

        # run mvn test
        if subprocess.run(["mvn", "test", "-Psmoke-test"]).returncode == 0:
            return 1.0
        return 0.0


class AgentPatchGrader(Grader):
    """
    A grader that tests agent patches by applying them and running tests.
    """

    name = "AgentPatchGrader"

    @classmethod
    def compute_score(
        cls,
        state: EnvironmentState,
        base: str,
        test: str,
        golden: str,
        playwright_test_files: list[str] | None = None,
        mocha_test_files: list[str] | None = None,
        test_files: list[str] | None = None,
        problem_id: str | None = None,
    ) -> tuple[float, dict]:
        """
        Compute a score based on whether the agent patch fixes the issue.

        Args:
            state: The current environment state
            base: The baseline branch/commit name (for metadata)
            test: The test branch/commit name (for metadata)
            golden: The golden branch/commit name (for metadata)
            test_files: List of test files to run
            problem_id: Problem ID to select patches. If not provided,
                       falls back to PROBLEM_ID env var.

        Returns:
            tuple: (score, metadata) where score is 1.0 if agent patch fixes the issue, 0.0 otherwise
        """
        # Create and run the grading runner
        # Resolve problem_id from parameter or environment
        resolved_problem_id = problem_id or os.environ.get("PROBLEM_ID")

        runner = GradingRunner(
            base=base,
            test=test,
            golden=golden,
            playwright_test_files=playwright_test_files,
            mocha_test_files=mocha_test_files,
            test_files=test_files,
            problem_id=resolved_problem_id,
        )

        success, metadata = runner.run_grading()
        score = 1.0 if success else 0.0

        # Return score and metadata as a tuple
        return (score, metadata)


class CodeFileGrader(Grader):
    """
    A grader that checks for the existence of code files with specific content.
    Note: This grader has been disabled as database functionality has been removed.
    """

    name = "CodeFileGrader"

    @classmethod
    def compute_score(
        cls, state: EnvironmentState, filename: str, content_check: str | None = None, table_name: str = "code_files"
    ) -> float:
        """
        Compute a score based on whether a code file exists and optionally contains specific content.

        Args:
            state: The current environment state
            filename: The name of the file to check
            content_check: Optional substring to check in file content
            table_name: The database table to query (ignored as database is disabled)

        Returns:
            float: 0.0 as database functionality is disabled
        """
        import logging

        logger = logging.getLogger(__name__)
        logger.warning("CodeFileGrader is disabled as database functionality has been removed")
        return 0.0


class FileSystemGrader(Grader):
    """
    A grader that checks if a file exists and optionally checks its content.
    """

    name = "FileSystemGrader"

    @classmethod
    def compute_score(
        cls, state: EnvironmentState, file_path: str, content_check: str | None = None
    ) -> Union[float, Tuple[float, Dict[str, Any]]]:
        """
        Compute a score based on whether a file exists and optionally contains specific content.

        Args:
            state: The current environment state
            file_path: Path to the file to check
            content_check: Optional string to check for in the file content

        Returns:
            tuple: (score, metadata) where score is 1.0 if conditions are met, 0.0 otherwise
        """
        import os

        metadata = {
            "file_path": file_path,
            "file_exists": False,
            "content_check": content_check,
            "content_found": False,
        }

        if not os.path.exists(file_path):
            return (0.0, metadata)

        metadata["file_exists"] = True

        if content_check is None:
            return (1.0, metadata)

        try:
            with open(file_path, "r") as f:
                content = f.read()
                metadata["file_size"] = len(content)
                if content_check in content:
                    metadata["content_found"] = True
                    return (1.0, metadata)
        except Exception as e:
            metadata["error"] = str(e)
            return (0.0, metadata)

        return (0.0, metadata)


class DirectoryGrader(Grader):
    """
    A grader that checks for directories and their contents.
    """

    name = "DirectoryGrader"

    @classmethod
    def compute_score(
        cls, state: EnvironmentState, dir_path: str, file_count: int | None = None, file_pattern: str | None = None
    ) -> float:
        """
        Compute a score based on whether a directory exists and optionally has specific contents.

        Args:
            state: The current environment state
            dir_path: The path to the directory to check
            file_count: Optional minimum number of files required
            file_pattern: Optional pattern to match files (e.g., "*.py")

        Returns:
            float: 1.0 if directory exists (and meets criteria if specified), 0.0 otherwise
        """

        if not os.path.exists(dir_path) or not os.path.isdir(dir_path):
            return 0.0

        if file_count is not None:
            files = os.listdir(dir_path)
            if len(files) < file_count:
                return 0.0

        if file_pattern:
            pattern = os.path.join(dir_path, file_pattern)
            matching_files = glob.glob(pattern)
            if not matching_files:
                return 0.0

        return 1.0
