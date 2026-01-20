#!/usr/bin/env python3
"""
Grading runner script for agent patch testing.

This script:
1. Creates a copy of the git repo at baseline commit in /tmp
2. Applies test.patch to this repo (tests should fail)
3. Applies agent.patch to this repo (tests should pass)
4. Generates JUnit XML report at /tmp/grading_results.xml
"""

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from packaging import version

from .constants import SAMPLE_REPO_URL
from .utils import merge_junits

logger = logging.getLogger(__name__)

class GradingRunner:
    """Handles the grading workflow for agent patch testing."""

    def __init__(
        self,
        base: str,
        test: str,
        golden: str,
        playwright_test_files: list[str] | None = None,
        mocha_test_files: list[str] | None = None,  # Warning: ignored for now
        test_files: list[str] | None = None,
        problem_id: str | None = None,
        patches_base_dir: str = "/home/root/patches",
        only_server: bool = False,
    ):
        """
        Initialize the grading runner.

        Args:
            base: The baseline branch name (for logging/metadata)
            test: The test branch name (for logging/metadata)
            golden: The golden branch name (for logging/metadata)
            test_files: List of test files to run
            problem_id: Problem ID to select patches from patches_base_dir.
                       If not provided, falls back to PROBLEM_ID env var.
            patches_base_dir: Base directory containing problem patches
                             (default: /home/root/patches)
            only_server: Whether to only start the server without running tests
        """
        # Determine what to use - branches take precedence
        self.use_base = base
        self.use_test = test
        self.use_golden = golden
        self.test_files = test_files or []
        self.only_server = only_server
        self.grade_working_dir = "/tmp/grading_workspace_" + str(uuid.uuid4())
        self.original_repo_path = os.environ.get("REPO_PATH", "/home/ubuntu/[PROJECT_NAME]")

        # Resolve problem_id from parameter or environment
        self.problem_id = problem_id or os.environ.get("PROBLEM_ID")

        if not self.problem_id:
            raise ValueError(
                "problem_id is required. Set PROBLEM_ID env var or pass problem_id parameter."
            )

        # Derive patch paths from problem_id
        self.test_patch_path = os.path.join(
            patches_base_dir, self.problem_id, "test.patch"
        )
        self.golden_patch_path = os.path.join(
            patches_base_dir, self.problem_id, "golden.patch"
        )
        logger.info(f"Using patches for problem '{self.problem_id}' from {patches_base_dir}")
        
        # Store references to server process and threads for cleanup
        self.server_process = None
        self.server_threads = []
        self.stop_threads = threading.Event()


    def _format_junit_xml(self, test_name: str, message: str, stdout: str, stderr: str) -> str:
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="{test_name}" tests="1" failures="1" errors="0" skipped="0">
    <testcase classname="{test_name}" name="test{test_name}" time="0.0">
      <failure type="TestFailure">\n{message}\n</failure>
      <system-out>\n{stdout}\n</system-out>
      <system-err>\n{stderr}\n</system-err>
    </testcase>
  </testsuite>
</testsuites>"""

    def run_tests(self) -> str:
        """
        Run tests and return JUnit XML output.
        
        CUSTOMIZE THIS METHOD for your test framework.
        
        The method should:
        1. Execute tests specified in self.test_files
        2. Generate JUnit XML output
        3. Return the XML content as a string
        
        Examples:
        
        === JEST (Node.js/TypeScript) ===
        command = f"yarn test -- --runInBand --verbose {' '.join(self.test_files)}"
        xml_file = "jest_results.xml"
        
        === PYTEST (Python) ===
        command = f"pytest --junit-xml=pytest_results.xml {' '.join(self.test_files)}"
        xml_file = "pytest_results.xml"
        
        === JUNIT (Java) ===
        command = f"mvn test -Dtest={','.join(self.test_files)}"
        xml_file = "target/surefire-reports/TEST-*.xml"
        
        === GTEST (C++) ===
        command = f"./test_runner --gtest_output=xml:gtest_results.xml --gtest_filter={':'.join(self.test_files)}"
        xml_file = "gtest_results.xml"
        
        === CARGO TEST (Rust) ===
        command = f"cargo test -- --format junit > cargo_results.xml"
        xml_file = "cargo_results.xml"
        """
        logger.info(f"Running tests in {self.grade_working_dir}")

        # [CUSTOMIZE] Remove this conditional block when customizing
        if os.environ.get("REPO_URL") == SAMPLE_REPO_URL:
            xml_file = "pytest_results.xml"
            # Use full path to pytest from the virtualenv
            test_command = f"/mcp_server/.venv/bin/python -m pytest --junit-xml={xml_file} {' '.join(self.test_files)}"
        else:
            # [CUSTOMIZE] Set your test command here
            test_command = "[TEST_COMMAND] " + " ".join(self.test_files)
            # [CUSTOMIZE] Set your test results XML file path
            xml_file = "[TEST_RESULTS_XML_FILE]"

        result = subprocess.run(
            ["sudo", "-u", "ubuntu", "bash", "-lc", test_command],
            cwd=Path(self.grade_working_dir),
            capture_output=True,
            text=True,
        )
        
        logger.info(f"Tests completed with code: {result.returncode}")
        logger.info(f"Test output: {result.stdout}")
        logger.info(f"Test error: {result.stderr}")

        with open(Path(self.grade_working_dir) / xml_file) as f:
            return f.read()

    def _wait_for_server(self, host: str = "localhost", port: int = 3000, timeout: int = 600) -> bool:
        """Wait for server to be ready by checking if port is listening."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    result = sock.connect_ex((host, port))
                    if result == 0:
                        logger.info(f"Server is ready on {host}:{port}")
                        return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _cleanup_generated_files(self):
        """
        Remove generated files that may interfere with the build.
        
        CUSTOMIZE THIS METHOD for your project's build artifacts.
        
        This is useful when agents generate intermediate files that conflict
        with the build system (e.g., compiling TypeScript to JavaScript when
        using a bundler, or generating .pyc files that should be cleaned).
        
        Examples:
        
        === TYPESCRIPT → JAVASCRIPT ===
        Remove .js files generated from .ts files in specific directories
        
        === PYTHON ===
        find . -type f -name "*.pyc" -delete
        find . -type d -name "__pycache__" -delete
        
        === JAVA ===
        find . -type f -name "*.class" -delete
        
        === C++ ===
        rm -rf build/ *.o *.out
        
        Leave empty if no cleanup needed.
        """
        logger.info("Cleaning up generated files")
        
        # [CUSTOMIZE] Add your cleanup logic here
        # Example: self._cleanup_typescript_js_files()
        
        pass  # Remove this when implementing cleanup

    def _needs_server_start(self) -> bool:
        """Check if current version needs server to be started for tests."""
        # [CUSTOMIZE] Remove this conditional block when customizing
        if os.environ.get("REPO_URL") == SAMPLE_REPO_URL:
            return False  # Sample repo tests don't need a server

        try:
            # Read package.json version from the working directory
            package_json_path = Path(self.grade_working_dir) / "package.json"
            with open(package_json_path) as f:
                package_data = json.load(f)

            current_version = package_data.get("version", "0.0.0")

            # At least version 0.66.2 (may be larger, im using attachmentsvalidation_baseline as a reference)
            threshold_version = "0.66.2"

            needs_server = version.parse(current_version) <= version.parse(threshold_version)
            logger.info(f"Current version: {current_version}, Server needed: {needs_server} (version {'<=' if needs_server else '>'} {threshold_version})")
            return needs_server

        except Exception as e:
            logger.warning(f"Error checking package.json version: {e}, assuming server needed")
            return True

    def run_grading(self) -> tuple[bool, dict]:
        """Run the complete grading workflow."""
        logger.info("Starting grading workflow")
        # Step 1: Copy original repo to working dir (as root to access .git)
        logger.info(f"Copying original repo to {self.grade_working_dir}")
        # Use trailing slash to copy contents, not the directory itself
        subprocess.run(["cp", "-rT", self.original_repo_path, self.grade_working_dir], check=True)
        # Make the copy accessible to ubuntu for test execution
        subprocess.run(["chown", "-R", "ubuntu:ubuntu", self.grade_working_dir], check=True)
        logger.info(f"Copied original repo to {self.grade_working_dir}")

        # Step 2: apply test patch
        logger.info(f"Applying test patch to {self.grade_working_dir}")
        with open(self.test_patch_path) as f:
            subprocess.run(["git", "apply"], check=True, cwd=self.grade_working_dir, input=f.read().encode("utf-8"))
        logger.info(f"Applied test patch to {self.grade_working_dir}")

        # Step 3: Clean up any generated files that might interfere with the build
        self._cleanup_generated_files()

        # Step 4: compile the project (should work if the agent code compiles)
        logger.info(f"Compiling project in {self.grade_working_dir}")
        
        # [CUSTOMIZE] Set your build command
        # Examples:
        #   Node.js: "NODE_OPTIONS=\"--max-old-space-size=4096\" yarn build" or "npm run build"
        #   Python: (often no build step needed)  or "python setup.py build"
        #   Java: "mvn package -DskipTests"
        #   Rust: "cargo build --release"
        #   C++: "cd build && cmake .. && make"

        # [CUSTOMIZE] Remove this conditional block when customizing
        if os.environ.get("REPO_URL") == SAMPLE_REPO_URL:
            build_command = "true"  # No build needed for sample Python repo
        else:
            build_command = "[BUILD_COMMAND]"
        
        # Run build and stream output to stderr in real-time
        build_process = subprocess.Popen(
            ["sudo", "-u", "ubuntu", "bash", "-lc", build_command],
            cwd=self.grade_working_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        
        # Collect output for error reporting while streaming
        build_output = []
        
        def stream_build_stdout():
            """Stream stdout to stderr while collecting for error reporting."""
            for line in build_process.stdout:
                sys.stderr.write(line)
                sys.stderr.flush()
                build_output.append(line)
        
        def stream_build_stderr():
            """Stream stderr to stderr while collecting for error reporting."""
            for line in build_process.stderr:
                sys.stderr.write(line)
                sys.stderr.flush()
                build_output.append(line)
        
        # Start streaming threads
        stdout_thread = threading.Thread(target=stream_build_stdout)
        stderr_thread = threading.Thread(target=stream_build_stderr)
        
        stdout_thread.start()
        stderr_thread.start()
        
        # Wait for threads to complete
        stdout_thread.join()
        stderr_thread.join()
        
        # Wait for the process to complete
        build_result_code = build_process.wait()
        
        # Check exit code
        if build_result_code != 0:
            # Format compile error as JUnit XML
            xml_content = self._format_junit_xml("AgentPatchCompiles", "Agent patch compilation failed", "".join(build_output), "")
            logger.info(f"Compilation failed with exit code {build_result_code}")
            return False, {"junit": xml_content}
        
        logger.info(f"Compiled project successfully in {self.grade_working_dir}")

        # Step 5: Reset test database and run migrations
        db_name = os.environ.get("TEST_DB_NAME", "test_db")
        logger.info(f"Resetting {db_name} database via psql")
        drop_cmd = (
            f"PGPASSWORD=ubuntu psql -h localhost -U ubuntu -c \"DROP DATABASE IF EXISTS {db_name};\""
        )
        create_cmd = (
            f"PGPASSWORD=ubuntu psql -h localhost -U ubuntu -c \"CREATE DATABASE {db_name};\""
        )
        
        # [CUSTOMIZE] Set your migration command (or set to None if not needed)
        # Examples:
        #   Node.js/Sequelize: "export NODE_ENV=test && yarn db:migrate"
        #   Django: "python manage.py migrate --noinput"
        #   Rails: "bundle exec rake db:migrate"
        #   Prisma: "npx prisma migrate deploy"

        # [CUSTOMIZE] Remove this conditional block when customizing
        if os.environ.get("REPO_URL") == SAMPLE_REPO_URL:
            migrate_cmd = None  # No database for sample Python repo
        else:
            migrate_cmd = "[MIGRATION_COMMAND]"  # Or None if no migrations

        if migrate_cmd:
            drop_res = subprocess.run(["bash", "-lc", drop_cmd], cwd=self.grade_working_dir, capture_output=True, text=True)
            logger.info(f"Drop DB exit: {drop_res.returncode}\n{drop_res.stdout}\n{drop_res.stderr}")
            create_res = subprocess.run(["bash", "-lc", create_cmd], cwd=self.grade_working_dir, capture_output=True, text=True)
            logger.info(f"Create DB exit: {create_res.returncode}\n{create_res.stdout}\n{create_res.stderr}")
            migrate_res = subprocess.run(["sudo", "-u", "ubuntu", "bash", "-lc", migrate_cmd], cwd=self.grade_working_dir, capture_output=True, text=True)
            logger.info(f"Migrate exit: {migrate_res.returncode}\n{migrate_res.stdout}\n{migrate_res.stderr}")
        else:
            logger.info("Skipping database setup (no migration command configured)")

        # Step 6: Conditionally start server based on version
        if self._needs_server_start():
            # [CUSTOMIZE] Set your server start command
            # Examples:
            #   Node.js: "yarn start" or "npm start"
            #   Django: "python manage.py runserver 3000"
            #   Flask: "flask run --port=3000"
            #   Spring Boot: "java -jar target/app.jar --server.port=3000"
            server_start_cmd = "[SERVER_START_COMMAND]"
            
            logger.info(f"Starting server with {server_start_cmd} (required for this version)")
            self.server_process = subprocess.Popen(
                ["sudo", "-u", "ubuntu", "bash", "-lc", server_start_cmd],
                cwd=self.grade_working_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            
            # Wait for server to be ready
            if not self._wait_for_server():
                logger.error("Server failed to start within timeout")
                if self.server_process:
                    self.server_process.terminate()
                xml_content = self._format_junit_xml("ServerStart", "Server failed to start within timeout", "", "")
                return False, {"junit": xml_content}
        else:
            logger.info("Skipping server start (not required for this version)")

        # Step 7: Run tests
        junit_xmls = [self.run_tests()]
        
        # Cleanup: Stop server if it was started
        if self.server_process:
            logger.info("Stopping server")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server_process.kill()

        merged_junit, full_success = merge_junits(junit_xmls)
        return full_success, {"junit": merged_junit}