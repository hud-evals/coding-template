"""
Grading runner for agent patch testing.

Workflow:
1. grade() calls:
   - Copy repo, strip agent-injected pytest hooks, apply test.patch
   - run_tests() [customize this]
   - Returns score (0.0 or 1.0)
"""

import logging
import os
import shutil
import subprocess
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

# Agent-writable paths that can change pytest's exit code without fixing the bug.
_PYTEST_INJECTION_GLOBS = (
    "**/conftest.py",
    "**/pytest.ini",
    "**/.pytest.ini",
    "**/tox.ini",
    "**/pytest.py",
    "**/sitecustomize.py",
)


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
        patches_dir: str | None = None,
        repo_path: str | None = None,
    ):
        self.problem_id = problem_id
        self.test_command = test_command
        self.test_files = test_files or []
        # Honor PROJECT_DIR / PATCHES_DIR (set by env.py) so grading uses the same
        # paths the agent edited — works both in the built image (absolute paths)
        # and locally (a writable dir next to env.py).
        self.patches_dir = patches_dir or os.environ.get("PATCHES_DIR", "/home/root/patches")
        self.repo_path = (
            repo_path
            or os.environ.get("PROJECT_DIR")
            or f"/home/ubuntu/{os.environ.get('FOLDER_NAME', 'project')}"
        )
        self.working_dir = f"/tmp/grading_{uuid.uuid4()}"

    @property
    def test_patch(self) -> str:
        return os.path.join(self.patches_dir, self.problem_id, "test.patch")

    def _strip_pytest_injections(self) -> list[str]:
        """Drop agent-added pytest hooks; restore any that were already on HEAD.

        An agent can write ``conftest.py`` that skips every test or forces
        ``session.exitstatus = 0``. Both make ``pytest`` exit 0 while the bug
        remains. Remove untracked injections and put tracked ones back to HEAD.
        """
        root = Path(self.working_dir)
        removed: list[str] = []
        tracked: list[str] = []
        for pattern in _PYTEST_INJECTION_GLOBS:
            for path in root.glob(pattern):
                if not path.is_file():
                    continue
                rel = str(path.relative_to(root))
                # Is this path tracked on HEAD?
                check = subprocess.run(
                    ["git", "ls-files", "--error-unmatch", rel],
                    cwd=self.working_dir,
                    capture_output=True,
                    text=True,
                )
                if check.returncode == 0:
                    tracked.append(rel)
                else:
                    path.unlink()
                    removed.append(rel)

        if tracked:
            restore = subprocess.run(
                ["git", "checkout", "HEAD", "--", *tracked],
                cwd=self.working_dir,
                capture_output=True,
                text=True,
            )
            if restore.returncode != 0:
                logger.warning(
                    "Could not restore tracked pytest files %s: %s",
                    tracked,
                    restore.stderr.strip(),
                )
            else:
                removed.extend(f"restored:{r}" for r in tracked)

        if removed:
            logger.info("Stripped pytest injection points: %s", removed)
        return removed

    def grade(self) -> float:
        """
        Run grading and return score.

        Returns:
            1.0 if tests pass, 0.0 otherwise
        """
        try:
            # Copy repo to grading workspace. (shutil.copytree is cross-platform —
            # the previous `cp -rT` used a GNU-only flag that BSD/macOS cp rejects.)
            logger.info(f"Copying repo to {self.working_dir}")
            shutil.copytree(self.repo_path, self.working_dir, symlinks=True)

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

            self._strip_pytest_injections()

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
            logger.info("Test metadata: %s", {k: metadata[k] for k in metadata if k not in ("stdout", "stderr")})

            return 1.0 if success else 0.0
        finally:
            # Never leave the patched copy (which contains the hidden tests) on
            # disk — on an unisolated host (local macOS) a later rollout's agent
            # could read it via `find /`.
            shutil.rmtree(self.working_dir, ignore_errors=True)

    # =========================================================================
    # CUSTOMIZE THIS
    # =========================================================================

    def run_tests(self) -> tuple[bool, dict]:
        """
        Run tests and return results. Override this for custom logic.

        Success requires a real pass: JUnit must show at least one test, zero
        failures, zero errors, and zero skips. Exit code alone is not enough:
        an agent can force exit 0 from conftest while every assertion still fails.
        """
        junit_path = Path(self.working_dir) / f".hud-junit-{uuid.uuid4().hex}.xml"
        files = " ".join(self.test_files)
        # Prefer the configured command, but always append a junit flag the
        # default pytest understands. Custom commands that already write junit
        # can override run_tests entirely.
        base = self.test_command.format(test_files=files)
        if "pytest" in base and "--junitxml" not in base:
            cmd = f"{base} --junitxml={junit_path}"
        else:
            cmd = base

        logger.info(f"Running: {cmd}")

        env = os.environ.copy()
        # Block third-party pytest plugins the agent might have dropped on PYTHONPATH.
        env.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

        result = subprocess.run(
            ["bash", "-lc", cmd],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
            env=env,
        )

        meta: dict = {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

        if not junit_path.is_file():
            meta["error"] = "test command did not write JUnit XML"
            return False, meta

        try:
            summary = _junit_summary(junit_path)
        except (OSError, ET.ParseError, ValueError) as exc:
            meta["error"] = f"bad JUnit XML: {exc}"
            return False, meta
        finally:
            junit_path.unlink(missing_ok=True)

        meta.update(summary)
        ok = (
            summary["tests"] > 0
            and summary["failures"] == 0
            and summary["errors"] == 0
            and summary["skipped"] == 0
        )
        return ok, meta


def _junit_summary(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    # pytest may write <testsuites> or a single <testsuite>
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        raise ValueError("no testsuite elements")
    tests = failures = errors = skipped = 0
    for s in suites:
        tests += int(s.attrib.get("tests", 0))
        failures += int(s.attrib.get("failures", 0))
        errors += int(s.attrib.get("errors", 0))
        skipped += int(s.attrib.get("skipped", 0))
    return {
        "tests": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    }
