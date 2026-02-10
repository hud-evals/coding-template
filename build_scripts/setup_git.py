#!/usr/bin/env python3
"""
Build-time git setup for the git-enabled coding template.

Reads task_config.yaml and prepares the cloned repo for agent access:
1. Extracts test.patch and golden.patch for each task
2. Converts needed remote branches to local branches
3. Deletes grading branches (test/golden) from the repo
4. Removes the origin remote (cleans up all origin/* refs)
5. Applies snapshot_before date filtering if configured
6. Runs git gc to purge deleted objects from packfiles
7. Leaves .git fully accessible to the agent (uid 1000 / ubuntu)

Usage (called from Dockerfile.hud):
    python3 /build_scripts/setup_git.py /home/ubuntu/project /home/root/patches

Environment:
    FOLDER_NAME: project folder name (default: "project")
"""

import logging
import os
import subprocess
import sys

logging.basicConfig(level=logging.INFO, format="[setup_git] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# YAML parser (minimal, no external dependency)
# ---------------------------------------------------------------------------

def _parse_yaml_simple(path: str) -> dict:
    """Parse a simple YAML file without requiring PyYAML.

    Supports the subset used by task_config.yaml:
    - Top-level mapping
    - Nested mappings (2-space indent)
    - Scalar values and simple lists (- item)
    - Comments (#) and blank lines

    Falls back to PyYAML if available.
    """
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        pass

    # Minimal built-in parser for the config subset we use
    with open(path) as f:
        lines = f.readlines()

    result: dict = {}
    stack: list[tuple[int, dict]] = [(-1, result)]

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.split("#")[0].rstrip()  # remove comments
        i += 1

        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())

        # Pop stack to find parent at correct indent level
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()

        parent = stack[-1][1]

        # List item: "- value"
        if stripped.lstrip().startswith("- "):
            value = stripped.lstrip()[2:].strip().strip('"').strip("'")
            # Find the key this list belongs to (last key added to parent)
            for key in reversed(list(parent.keys())):
                if isinstance(parent[key], list):
                    parent[key].append(value)
                    break
                elif parent[key] is None or parent[key] == "":
                    parent[key] = [value]
                    break
            continue

        # Key: value or Key:
        if ":" in stripped:
            colon_idx = stripped.index(":")
            key = stripped[:colon_idx].strip()
            val = stripped[colon_idx + 1:].strip()

            if val == "" or val == "|":
                # Nested mapping or empty value
                parent[key] = {}
                stack.append((indent, parent[key]))
            elif val.startswith("[") and val.endswith("]"):
                # Inline list: [item1, item2]
                items = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
                parent[key] = items
            elif val.startswith('"') and val.endswith('"'):
                parent[key] = val[1:-1]
            elif val.startswith("'") and val.endswith("'"):
                parent[key] = val[1:-1]
            else:
                parent[key] = val

    return result


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git(repo_dir: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the given repo directory."""
    cmd = ["git", "-C", repo_dir, "-c", f"safe.directory={repo_dir}", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        logger.error("git %s failed: %s", " ".join(args), result.stderr.strip())
        if check:
            result.check_returncode()
    return result


def get_remote_branches(repo_dir: str) -> list[str]:
    """Get all remote branch names (without 'origin/' prefix)."""
    result = git(repo_dir, "branch", "-r", "--format=%(refname:short)", check=False)
    branches = []
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if line and not line.endswith("/HEAD"):
            # Strip "origin/" prefix
            if line.startswith("origin/"):
                branches.append(line[7:])
            else:
                branches.append(line)
    return branches


def get_local_branches(repo_dir: str) -> list[str]:
    """Get all local branch names."""
    result = git(repo_dir, "branch", "--format=%(refname:short)", check=False)
    return [b.strip() for b in result.stdout.strip().splitlines() if b.strip()]


def branch_exists_remote(repo_dir: str, branch: str) -> bool:
    """Check if a remote branch exists."""
    result = git(repo_dir, "rev-parse", "--verify", f"origin/{branch}", check=False)
    return result.returncode == 0


def extract_patch(repo_dir: str, base_branch: str, target_branch: str) -> str:
    """Generate a patch from base_branch to target_branch. Returns patch content."""
    result = git(repo_dir, "diff", f"origin/{base_branch}", f"origin/{target_branch}")
    return result.stdout


def create_local_branch(repo_dir: str, branch_name: str, source: str = "") -> None:
    """Create a local branch from a remote tracking branch."""
    source = source or f"origin/{branch_name}"
    # Check if local branch already exists
    existing = get_local_branches(repo_dir)
    if branch_name in existing:
        # Update it to point to the right commit
        git(repo_dir, "branch", "-f", branch_name, source)
    else:
        git(repo_dir, "branch", branch_name, source)


def apply_snapshot(repo_dir: str, branch: str, before_date: str) -> None:
    """Truncate a branch to only include commits before the given date."""
    result = git(repo_dir, "rev-list", "-1", f"--before={before_date}", branch, check=False)
    commit = result.stdout.strip()
    if not commit:
        logger.warning("No commits found before %s on branch %s, skipping snapshot", before_date, branch)
        return
    logger.info("Truncating branch %s to commit %s (before %s)", branch, commit[:8], before_date)
    git(repo_dir, "branch", "-f", branch, commit)


# ---------------------------------------------------------------------------
# Main logic
# ---------------------------------------------------------------------------

def setup_git(repo_dir: str, patches_dir: str, config_path: str) -> None:
    """Main entry point: prepare the repo for agent access."""
    logger.info("Setting up git-enabled repo: %s", repo_dir)
    logger.info("Patches directory: %s", patches_dir)
    logger.info("Config: %s", config_path)

    if not os.path.exists(config_path):
        logger.warning("No task_config.yaml found at %s, skipping git setup", config_path)
        return

    config = _parse_yaml_simple(config_path)
    tasks = config.get("tasks", {})

    if not tasks:
        logger.warning("No tasks defined in task_config.yaml, skipping git setup")
        return

    # Fetch all remote branches
    git(repo_dir, "fetch", "--all", check=False)

    # Collect all branches we need across all tasks
    branches_to_keep: set[str] = set()
    branches_to_hide: set[str] = set()
    snapshot_configs: dict[str, str] = {}  # branch -> date

    for task_id, task_cfg in tasks.items():
        if not isinstance(task_cfg, dict):
            logger.warning("Skipping non-dict task config: %s", task_id)
            continue

        worktree = task_cfg.get("worktree", {})
        grading = task_cfg.get("grading", {})

        if not isinstance(worktree, dict) or not isinstance(grading, dict):
            logger.warning("Skipping task %s: worktree or grading is not a dict", task_id)
            continue

        # Branches the agent should see
        checkout_branch = worktree.get("checkout", "")
        if checkout_branch:
            branches_to_keep.add(checkout_branch)

        include_branches = worktree.get("include_branches")
        if isinstance(include_branches, list):
            branches_to_keep.update(include_branches)

        # Grading branches to hide
        test_branch = grading.get("test_branch", "")
        golden_branch = grading.get("golden_branch", "")
        if test_branch:
            branches_to_hide.add(test_branch)
        if golden_branch:
            branches_to_hide.add(golden_branch)

        # Snapshot config
        snapshot_before = worktree.get("snapshot_before", "")
        if snapshot_before and checkout_branch:
            snapshot_configs[checkout_branch] = snapshot_before

    logger.info("Branches to keep: %s", branches_to_keep)
    logger.info("Branches to hide: %s", branches_to_hide)

    # -------------------------------------------------------------------------
    # Step 1: Extract patches for each task
    # -------------------------------------------------------------------------
    for task_id, task_cfg in tasks.items():
        if not isinstance(task_cfg, dict):
            continue

        worktree = task_cfg.get("worktree", {})
        grading = task_cfg.get("grading", {})

        if not isinstance(worktree, dict) or not isinstance(grading, dict):
            continue

        checkout_branch = worktree.get("checkout", "")
        test_branch = grading.get("test_branch", "")
        golden_branch = grading.get("golden_branch", "")

        if not checkout_branch:
            logger.error("Task %s: missing worktree.checkout", task_id)
            continue

        task_patches_dir = os.path.join(patches_dir, task_id)
        os.makedirs(task_patches_dir, exist_ok=True)

        # Extract test.patch (checkout → test)
        if test_branch and branch_exists_remote(repo_dir, test_branch):
            logger.info("Task %s: extracting test.patch (%s → %s)", task_id, checkout_branch, test_branch)
            patch = extract_patch(repo_dir, checkout_branch, test_branch)
            patch_path = os.path.join(task_patches_dir, "test.patch")
            with open(patch_path, "w") as f:
                f.write(patch)
            logger.info("  → %s (%d bytes)", patch_path, len(patch))
        else:
            logger.warning("Task %s: test_branch '%s' not found, skipping test.patch", task_id, test_branch)

        # Extract golden.patch (checkout → golden)
        if golden_branch and branch_exists_remote(repo_dir, golden_branch):
            logger.info("Task %s: extracting golden.patch (%s → %s)", task_id, checkout_branch, golden_branch)
            patch = extract_patch(repo_dir, checkout_branch, golden_branch)
            patch_path = os.path.join(task_patches_dir, "golden.patch")
            with open(patch_path, "w") as f:
                f.write(patch)
            logger.info("  → %s (%d bytes)", patch_path, len(patch))
        else:
            logger.warning("Task %s: golden_branch '%s' not found, skipping golden.patch", task_id, golden_branch)

    # -------------------------------------------------------------------------
    # Step 2: Determine which branches to keep
    # -------------------------------------------------------------------------
    all_remote = set(get_remote_branches(repo_dir))
    logger.info("All remote branches: %s", all_remote)

    # If no include_branches specified for ANY task, keep all except hidden ones
    has_explicit_includes = any(
        isinstance(t.get("worktree", {}).get("include_branches"), list)
        for t in tasks.values()
        if isinstance(t, dict)
    )

    if has_explicit_includes:
        # Only keep explicitly listed branches
        final_keep = branches_to_keep - branches_to_hide
    else:
        # Keep everything except grading branches
        final_keep = all_remote - branches_to_hide

    logger.info("Final branches to keep as local: %s", final_keep)

    # -------------------------------------------------------------------------
    # Step 3: Create local branches for everything we want to keep
    # -------------------------------------------------------------------------
    for branch in final_keep:
        if branch_exists_remote(repo_dir, branch):
            logger.info("Creating local branch: %s", branch)
            create_local_branch(repo_dir, branch)
        else:
            logger.warning("Branch %s not found in remote, skipping", branch)

    # -------------------------------------------------------------------------
    # Step 4: Remove the origin remote (cleans up all origin/* refs)
    # -------------------------------------------------------------------------
    logger.info("Removing origin remote")
    git(repo_dir, "remote", "remove", "origin", check=False)

    # -------------------------------------------------------------------------
    # Step 5: Delete any local branches that shouldn't be visible
    # -------------------------------------------------------------------------
    remaining_local = set(get_local_branches(repo_dir))
    to_delete = remaining_local - final_keep
    if to_delete:
        logger.info("Deleting local branches: %s", to_delete)
        # First checkout one of the kept branches so we're not on a branch we're deleting
        first_keep = next(iter(final_keep)) if final_keep else None
        if first_keep:
            git(repo_dir, "checkout", first_keep, check=False)

        for branch in to_delete:
            git(repo_dir, "branch", "-D", branch, check=False)

    # -------------------------------------------------------------------------
    # Step 6: Apply snapshot_before date filtering
    # -------------------------------------------------------------------------
    for branch, date_str in snapshot_configs.items():
        if branch in final_keep:
            apply_snapshot(repo_dir, branch, date_str)

    # -------------------------------------------------------------------------
    # Step 7: Checkout the first task's starting branch
    # -------------------------------------------------------------------------
    # Find the first task's checkout branch and set it as HEAD
    for task_id, task_cfg in tasks.items():
        if not isinstance(task_cfg, dict):
            continue
        worktree = task_cfg.get("worktree", {})
        if isinstance(worktree, dict):
            checkout = worktree.get("checkout", "")
            if checkout and checkout in final_keep:
                logger.info("Setting HEAD to: %s", checkout)
                git(repo_dir, "checkout", checkout, check=False)
                break

    # -------------------------------------------------------------------------
    # Step 8: Clean up - purge deleted objects
    # -------------------------------------------------------------------------
    logger.info("Cleaning up: expiring reflogs and running gc")
    git(repo_dir, "reflog", "expire", "--expire=now", "--all", check=False)
    git(repo_dir, "gc", "--prune=now", "--aggressive", check=False)

    # -------------------------------------------------------------------------
    # Step 9: Verify final state
    # -------------------------------------------------------------------------
    final_branches = get_local_branches(repo_dir)
    logger.info("Final repo state:")
    logger.info("  Local branches: %s", final_branches)

    result = git(repo_dir, "log", "--oneline", "-5", check=False)
    for line in result.stdout.strip().splitlines():
        logger.info("  %s", line)

    logger.info("Git setup complete!")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <repo_dir> <patches_dir> [config_path]")
        print(f"  repo_dir:    Path to the cloned repo (e.g. /home/ubuntu/project)")
        print(f"  patches_dir: Path to store patches (e.g. /home/root/patches)")
        print(f"  config_path: Path to task_config.yaml (default: /build_scripts/task_config.yaml)")
        sys.exit(1)

    repo_dir = sys.argv[1]
    patches_dir = sys.argv[2]
    config_path = sys.argv[3] if len(sys.argv) > 3 else "/build_scripts/task_config.yaml"

    setup_git(repo_dir, patches_dir, config_path)
