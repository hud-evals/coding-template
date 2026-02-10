# Implementation Plan: Git-Enabled Coding Template

## Overview

This is a fork of `hud-evals/coding-template` that gives AI agents **full git access** during evaluations.
The original template locks `.git` (root-only permissions) so agents can't use `git log`, `git blame`, etc.
This template removes that restriction, enabling more realistic SDLC-style evaluations where agents can
use git as a debugging and investigation tool — just like real engineers do.

## Problem Statement

The original coding-template's 3-branch pattern (baseline/test/golden) puts all branches in the same repo,
then locks `.git` to prevent agents from peeking at the solution. This is overly restrictive:

- Real engineers use `git log -p -- file.py` to trace when bugs were introduced
- `git blame` pinpoints problematic lines to their commit
- `git diff HEAD~5` shows recent changes
- `git stash` / `git commit` let engineers checkpoint their work

Blocking git makes evaluations unrealistic and handicaps agents unnecessarily.

## Solution

**Separate what the agent sees from what grading needs:**

1. At **build time**: extract test/golden patches, then **delete** those branches from the repo
2. The agent gets a repo with full `.git` access but no way to see the answer
3. **Grading** still uses the pre-extracted patches (stored in a root-only directory)

## Architecture

### Build Time (Docker)

```
Clone repo (all branches)
    → setup_git.py reads task_config.yaml
    → Extracts test.patch + golden.patch into /home/root/patches/ (root-only)
    → Converts needed remote branches → local branches
    → Deletes golden/test branches + all remote refs
    → git gc --prune=now (purges deleted objects from packfiles)
    → .git stays owned by ubuntu (agent-accessible)
```

### Runtime (Scenario Start)

```
setup_task()
    → Sets PROBLEM_ID env var
    → git checkout <starting_branch>  (local branch, already exists)
    → For golden_pass validation: git apply golden.patch
    → Agent has full git access
```

### Grading (After Agent Finishes)

```
GradingRunner.grade()
    → cp -rT repo /tmp/grading_<uuid>/   (includes .git)
    → git apply test.patch                (injects hidden test files)
    → Run test command
    → Return 1.0 or 0.0
```

## File Changes

### NEW Files

| File | Purpose |
|------|---------|
| `task_config.yaml` | Per-task git configuration: which branches the agent sees, grading branches, snapshot dates |
| `build_scripts/setup_git.py` | Build-time script: extract patches, prune branches, clean up refs, gc |
| `IMPLEMENTATION_PLAN.md` | This file |

### MODIFIED Files

| File | What Changes |
|------|-------------|
| `Dockerfile.hud` | Remove `.git` lockdown, add `setup_git.py` call, COPY task_config.yaml |
| `env.py` | Simplify `setup_task()` (no runtime patch gen, no .git locking), update `make_prompt()` |
| `grading/runner.py` | Add `safe.directory` to git apply, store `last_metadata` |
| `grading/graders.py` | Return metadata from runner |
| `tasks/basic.py` | Update sample task for new pattern |
| `pyproject.toml` | Add `pyyaml` dependency |
| `README.md` | Rewrite for git-enabled workflow |
| `CUSTOMIZATION_GUIDE.md` | Document new configuration format |

### UNCHANGED Files

| File | Why |
|------|-----|
| `tools/bash.py` | Agent tools are the same |
| `tools/editor.py` | Agent tools are the same |
| `tools/base.py` | Agent tools are the same |
| `tools/run.py` | Agent tools are the same |
| `grading/spec.py` | Grade/SubGrade types unchanged |
| `imagectl4.py` | Validation logic unchanged (baseline_fail + golden_pass) |

## task_config.yaml Schema

```yaml
# task_config.yaml - Per-task git worktree configuration
#
# Each task declares:
#   - worktree: what the agent sees (branches, history cutoff)
#   - grading: hidden branches for test injection + validation

tasks:
  sample-json-bug:
    worktree:
      # Branch the agent starts on
      checkout: server_fix_baseline

      # Branches visible to the agent
      # If omitted: ALL branches except grading branches are kept
      include_branches:
        - server_fix_baseline

      # Optional: truncate history to commits before this date
      # Useful for "the repo as it was on date X" scenarios
      # snapshot_before: "2026-01-15T00:00:00Z"

    grading:
      # These branches are extracted as patches then DELETED from the repo
      test_branch: server_fix_test
      golden_branch: server_fix_golden

      # Test configuration
      test_files: ["test_server.py"]
      test_command: "uv run pytest {test_files}"
```

### Key Fields

| Field | Required | Description |
|-------|----------|-------------|
| `worktree.checkout` | Yes | Branch to checkout as agent's starting point |
| `worktree.include_branches` | No | Whitelist of branches to keep. If omitted, all non-grading branches are kept |
| `worktree.snapshot_before` | No | ISO 8601 date. Truncates branch history to commits before this date |
| `grading.test_branch` | Yes | Branch containing test files (extracted as patch, then deleted) |
| `grading.golden_branch` | Yes | Branch containing solution (extracted as patch, then deleted) |
| `grading.test_files` | Yes | List of test file paths (relative to repo root) |
| `grading.test_command` | No | Test command with `{test_files}` placeholder. Default: `uv run pytest {test_files}` |

## build_scripts/setup_git.py Logic

```
1. Parse task_config.yaml
2. For each task:
   a. Compute the set of branches to KEEP (checkout + include_branches)
   b. Compute the set of branches to HIDE (test_branch, golden_branch)
   c. Extract test.patch:  git diff origin/<checkout> origin/<test_branch>
   d. Extract golden.patch: git diff origin/<checkout> origin/<golden_branch>
   e. Write patches to /home/root/patches/<task_id>/
3. Collect ALL branches that need to be kept (union across all tasks)
4. Convert kept remote branches → local branches
5. Delete the origin remote (removes all origin/* refs)
6. Delete any remaining local branches that aren't in the keep set
7. If any task has snapshot_before:
   a. Find the last commit before that date on the checkout branch
   b. Reset the branch to that commit
8. git reflog expire --expire=now --all
9. git gc --prune=now --aggressive
```

## Key Design Decisions

### Agent CAN commit
The agent runs as uid 1000 (ubuntu). Since `.git` is owned by ubuntu, `git commit` works.
This is intentional — real engineers commit checkpoints while debugging.
The grading runner copies the repo as-is (including any agent commits) and applies the test patch on top.

### Agent CANNOT see the answer
Golden/test branches are deleted at build time. `git gc --prune=now --aggressive` removes the objects
from packfiles. There's nothing left to discover via `git reflog`, `git fsck`, or `git log --all`.

### `origin` remote is removed
The agent sees a local-only repo. No `origin/golden` refs to discover.
The repo looks like a normal local clone with just the branches they should see.

### Validation still works
- `baseline_fail`: Start on baseline, run 0 agent steps, tests should fail → inverted score = 1.0
- `golden_pass`: Start on baseline, apply golden.patch, run tests → score = 1.0
  (golden.patch is pre-built and stored in /home/root/patches/)

### Multi-task repos
Multiple tasks can reference the same cloned repo with different branch configurations.
`setup_git.py` processes all tasks and keeps the union of all needed branches.
At runtime, `setup_task()` checks out the right branch for the active task.

## Implementation Order

1. `task_config.yaml` — define the schema
2. `build_scripts/setup_git.py` — the core build-time logic
3. `Dockerfile.hud` — wire up the build script
4. `env.py` — simplify setup_task
5. `grading/runner.py` — minor git apply fix
6. `grading/graders.py` — return metadata
7. `tasks/basic.py` — update example
8. `pyproject.toml` — add pyyaml
9. `README.md` — rewrite docs
10. `CUSTOMIZATION_GUIDE.md` — update docs
