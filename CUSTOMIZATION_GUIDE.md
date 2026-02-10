# Customization Guide

## Creating New Tasks

Tasks in this git-enabled template follow the same 3-branch pattern as the original template,
but with two key differences:

1. **Git configuration is in `task_config.yaml`** (not hardcoded in scenarios)
2. **Agents have full git access** (`git log`, `git blame`, `git diff`, etc.)

### 1. Set up branches in your target repo

Each task needs 3 branches:
- `baseline` - Starting state (bug present, no tests)
- `test` - Adds test files that verify the fix
- `golden` - Contains the correct solution

### 2. Add the task to task_config.yaml

```yaml
tasks:
  my-task:
    worktree:
      checkout: my_task_baseline
      include_branches:
        - my_task_baseline
      # snapshot_before: "2026-01-15T00:00:00Z"  # Optional
    grading:
      test_branch: my_task_test
      golden_branch: my_task_golden
      test_files:
        - test_foo.py
      # test_command: "pytest {test_files} -v"  # Optional
```

### 3. Define the scenario

```python
# tasks/basic.py
from env import env, setup_task, make_prompt
from grading import AgentPatchGrader, Grade, ValidateMode

@env.scenario("my-task")
async def my_task(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Short description of the task."""

    setup_task(
        task_id="my-task",           # Must match key in task_config.yaml
        checkout="my_task_baseline",  # Branch the agent starts on
        validate_mode=validate_mode,
    )

    prompt = make_prompt("""Fix the bug in foo.py.

The function returns incorrect results when given negative numbers.
Use git log and git blame to investigate when the bug was introduced.
""")

    _ = yield prompt

    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="my-task",
            test_files=["test_foo.py"],
            validate_mode=validate_mode,
        )
    ])

    yield grade.score
```

### 4. Build and validate

```bash
uv run imagectl4.py -bv --ids my-task
```

### 5. Test with an agent

```bash
uv run imagectl4.py -r --ids my-task --max-steps 30
```

### 6. Combine all steps

```bash
uv run imagectl4.py -bvr --ids my-task
```

---

## task_config.yaml Reference

### Branch Visibility

**Explicit whitelist** (recommended for most tasks):
```yaml
worktree:
  checkout: baseline
  include_branches:
    - baseline
    - main
```

**Keep all non-grading branches** (omit `include_branches`):
```yaml
worktree:
  checkout: baseline
  # All branches except test/golden will be visible
```

### Snapshot Before (History Truncation)

Show the repo as it was on a specific date:
```yaml
worktree:
  checkout: main
  snapshot_before: "2026-01-15T00:00:00Z"
```

This finds the last commit before that date and resets the branch to it.
Useful for scenarios like "a regression was introduced sometime last week."

### Multi-Task Configuration

Multiple tasks can share the same repo with different configurations:
```yaml
tasks:
  fix-auth-bug:
    worktree:
      checkout: main
      include_branches: [main, develop]
    grading:
      test_branch: auth_test
      golden_branch: auth_golden
      test_files: [tests/test_auth.py]

  fix-api-bug:
    worktree:
      checkout: main
      include_branches: [main]
    grading:
      test_branch: api_test
      golden_branch: api_golden
      test_files: [tests/test_api.py]
```

The build script keeps the union of all branches across tasks.

---

## Adding Build Packages

Edit `Dockerfile.hud` to install packages needed for your project.
The git setup section runs before dependency installation, so you can
customize both independently.

### System packages (apt)

```dockerfile
RUN apt-get update && apt-get install -y \
    postgresql-client \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*
```

### Project dependencies

```dockerfile
# After WORKDIR /home/ubuntu/project
RUN pip install -r requirements.txt
```

---

## Customizing the Testing Flow

### Simple: Configure the test command

```yaml
# In task_config.yaml
grading:
  test_command: "pytest {test_files} -v"
```

Or in the scenario:
```python
AgentPatchGrader.grade(
    weight=1.0,
    problem_id="my-task",
    test_files=["test_foo.py"],
    test_command="yarn test {test_files}",
)
```

### Advanced: Custom test logic

Subclass `GradingRunner` and override `run_tests()`:

```python
import subprocess
from grading import GradingRunner

class MyRunner(GradingRunner):
    def run_tests(self) -> tuple[bool, dict]:
        # The agent may have made git commits — the working tree
        # reflects whatever state the agent left it in
        result = subprocess.run(
            ["yarn", "test", *self.test_files],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
```

---

## Differences from Original Template

| Aspect | Original (`coding-template`) | Git-Enabled (`coding-template-with-git`) |
|--------|-----|-----|
| Agent git access | None (`.git` locked) | Full (`log`, `blame`, `diff`, `commit`) |
| Patch extraction | Runtime (`setup_task()`) | Build time (`setup_git.py`) |
| `setup_task()` args | `task_id, base, test, golden` | `task_id, checkout` |
| Branch config | Hardcoded in scenarios | `task_config.yaml` |
| `.git` ownership | root (locked) | ubuntu (agent-accessible) |
| Solution hidden via | `.git` permissions | Branch deletion + `git gc` |
| Validation (`golden_pass`) | Checks out golden branch | Applies `golden.patch` |

### Migration from original template

To convert a task from the original template:

1. Add entry to `task_config.yaml` (move branch names there)
2. Simplify `setup_task()` call (remove `base`, `test`, `golden` args)
3. The grading logic stays identical

---

## Quick Reference

| File | Purpose |
|------|---------|
| `task_config.yaml` | Git/branch configuration per task |
| `tasks/*.py` | Task definitions (scenarios) |
| `grading/graders.py` | Grading logic |
| `grading/runner.py` | Test execution |
| `build_scripts/setup_git.py` | Build-time git setup |
| `Dockerfile.hud` | Build configuration |
| `env.py` | MCP server and tools |
| `imagectl4.py` | Build, validate, run, push, and JSON generation |
