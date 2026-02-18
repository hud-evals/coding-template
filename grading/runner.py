"""
Grading runner for agent patch testing.

Workflow:
1. grade() calls:
   - Copy repo, apply test.patch
   - run_tests() [customize this]
   - Returns score (0.0 or 1.0)
"""

import logging
import os
import subprocess
import uuid

logger = logging.getLogger(__name__)


class GradingRunner:
    """
    Grading runner.
    
    Usage:
        runner = GradingRunner(
            problem_id="my_task",
            test_command="pytest {test_files}",
            test_files=["test_foo.py"],
        )
        score = runner.grade()
    
    To customize, override run_tests():
        
        class MyRunner(GradingRunner):
            def run_tests(self) -> tuple[bool, dict]:
                result = subprocess.run(["make", "test"], cwd=self.working_dir)
                return result.returncode == 0, {}
    """

    def __init__(
        self,
        problem_id: str,
        test_command: str = "",
        test_files: list[str] | None = None,
        patches_dir: str = "/home/root/patches",
        repo_path: str | None = None,
    ):
        self.problem_id = problem_id
        self.test_command = test_command
        self.test_files = test_files or []
        self.patches_dir = patches_dir
        self.repo_path = repo_path or f"/home/ubuntu/{os.environ.get('FOLDER_NAME', 'project')}"
        self.working_dir = f"/tmp/grading_{uuid.uuid4()}"

    @property
    def test_patch(self) -> str:
        return os.path.join(self.patches_dir, self.problem_id, "test.patch")

    def grade(self) -> float:
        """
        Run grading and return score.
        
        Returns:
            1.0 if tests pass, 0.0 otherwise
        """
        # Copy repo to grading workspace
        logger.info(f"Copying repo to {self.working_dir}")
        subprocess.run(["cp", "-rT", self.repo_path, self.working_dir], check=True)

        # Refresh git index after cp (stat info is stale in the copy)
        refresh = subprocess.run(
            ["git", "update-index", "--refresh"],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
        )
        if refresh.returncode != 0:
            logger.warning(
                f"git update-index --refresh failed (exit {refresh.returncode}): "
                f"{refresh.stderr.strip()}"
            )
        else:
            logger.info("Git index refreshed")

        # Apply test patch (adds test files)
        logger.info(f"Applying test patch: {self.test_patch}")
        with open(self.test_patch) as f:
            patch_content = f.read()
        if not patch_content.strip():
            raise RuntimeError(
                f"Test patch is empty: {self.test_patch}. "
                "The test branch likely has no diff from the baseline branch."
            )

        patch_lines = patch_content.splitlines()
        logger.info(
            f"Patch stats: {len(patch_lines)} lines, "
            f"files: {[l for l in patch_lines if l.startswith('diff --git')]}"
        )

        result = subprocess.run(
            ["git", "apply", "--verbose"],
            cwd=self.working_dir,
            input=patch_content,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"git apply stdout: {result.stdout.strip()}")
            logger.error(f"git apply stderr: {result.stderr.strip()}")
            raise RuntimeError(
                f"git apply failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )

        # Run tests
        success, metadata = self.run_tests()
        
        return 1.0 if success else 0.0

    # =========================================================================
    # CUSTOMIZE THIS
    # =========================================================================

    def run_tests(self) -> tuple[bool, dict]:
        """
        Run tests and return results. Override this for custom logic.
        
        Returns:
            (success, metadata) - success is True if tests pass
        """
        cmd = self.test_command.format(test_files=" ".join(self.test_files))
        logger.info(f"Running: {cmd}")
        
        result = subprocess.run(
            ["bash", "-lc", cmd],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
        )

        return result.returncode == 0, {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
