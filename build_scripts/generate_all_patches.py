#!/usr/bin/env python3
"""
Generate test and golden patches for all registered problems.

This script is run during Docker build to pre-generate patches for all problems
in PROBLEM_REGISTRY. Patches are stored in /home/root/patches/{problem_id}/.

At runtime, the grading runner selects the appropriate patches based on the
problem_id scenario argument.
"""
import os
import subprocess
import sys

# Add the parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from grading import PROBLEM_REGISTRY
import tasks  # noqa: F401 - registers problems via @problem decorators

PATCHES_DIR = os.environ.get("PATCHES_DIR", "/home/root/patches")
REPO_DIR = os.environ.get("REPO_PATH", "/home/ubuntu/[PROJECT_NAME]")


def generate_patches():
    """Generate test and golden patches for all registered problems."""
    os.makedirs(PATCHES_DIR, exist_ok=True)

    # Track which branches we've already fetched
    fetched_branches = set()

    print(f"Generating patches for {len(PROBLEM_REGISTRY)} problems...")
    print(f"Repository: {REPO_DIR}")
    print(f"Output directory: {PATCHES_DIR}")
    print()

    for spec in PROBLEM_REGISTRY:
        problem_dir = os.path.join(PATCHES_DIR, spec.id)
        os.makedirs(problem_dir, exist_ok=True)

        # Ensure all required branches are available locally
        for branch in [spec.base, spec.test, spec.golden]:
            if branch not in fetched_branches:
                # Try to fetch the branch (may already exist locally)
                subprocess.run(
                    ["git", "fetch", "origin", branch],
                    cwd=REPO_DIR,
                    capture_output=True,
                    check=False,  # Don't fail if branch already exists
                )
                fetched_branches.add(branch)

        # Generate test patch: diff from baseline to test branch
        test_result = subprocess.run(
            ["git", "diff", f"origin/{spec.base}", f"origin/{spec.test}"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
        )

        test_patch_path = os.path.join(problem_dir, "test.patch")
        with open(test_patch_path, "w") as f:
            f.write(test_result.stdout)

        # Generate golden patch: diff from baseline to golden branch
        golden_result = subprocess.run(
            ["git", "diff", f"origin/{spec.base}", f"origin/{spec.golden}"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
        )

        golden_patch_path = os.path.join(problem_dir, "golden.patch")
        with open(golden_patch_path, "w") as f:
            f.write(golden_result.stdout)

        print(
            f"  {spec.id}: test.patch ({len(test_result.stdout)} bytes), "
            f"golden.patch ({len(golden_result.stdout)} bytes)"
        )

    print()
    print(f"Successfully generated patches for {len(PROBLEM_REGISTRY)} problems")


if __name__ == "__main__":
    generate_patches()
