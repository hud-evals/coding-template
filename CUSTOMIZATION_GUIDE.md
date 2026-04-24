# Customization Guide

## Creating New Tasks

This environment uses a single `coding-bug` scenario defined in `tasks.py`. Each task is a `.task()` call on that scenario, passing different parameters (task ID, description, test files). You don't need to define new scenarios — just add new `.task()` calls.

### 1. Set up branches in your target repo

Each task needs 3 branches following the naming convention `{task_id}_baseline`, `{task_id}_test`, `{task_id}_golden`:

- `{task_id}_baseline` - Starting state (bug present, no tests)
- `{task_id}_test` - Adds test files that verify the fix
- `{task_id}_golden` - Contains the correct solution

### 2. Add a task in `tasks.py`

Add a new `.task()` call on the existing `coding_bug` scenario and register it in the `tasks` dict:

```python
# In tasks.py

_my_task = coding_bug.task(
    task_id="my_task",
    description=(
        "Fix the bug in foo.py.\n\n"
        "The function returns incorrect results when given negative numbers."
    ),
    test_files=["test_foo.py"],
)
_my_task.slug = "my-task"

# Add to the tasks registry
tasks = {
    ...
    "my_task": _my_task,
}
```

### 3. Deploy, sync, and run

```bash
hud deploy .                            # deploy the environment (once)
hud sync tasks <taskset-name>           # push tasks to a taskset (re-run on every task change)
hud eval <taskset-name> --remote --full # run evaluation
```

Only redeploy when `env.py`, `Dockerfile.hud`, or system-level dependencies change. After that, edit `tasks.py` and re-run `hud sync tasks` (fast).

---

## Adding Build Packages

Edit `Dockerfile.hud` to install packages needed for your project.

### System packages (apt)

```dockerfile
# Near the top, after the base apt-get install
RUN apt-get update && apt-get install -y \
    postgresql-client \
    redis-tools \
    && rm -rf /var/lib/apt/lists/*
```

### Language runtimes

```dockerfile
# Node.js (uncomment and customize)
RUN bash -c "source ~/.nvm/nvm.sh && nvm install 20 && nvm alias default 20"

# Python packages
RUN pip install pytest numpy pandas

# Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
```

### Project dependencies

```dockerfile
# After WORKDIR /home/ubuntu/project

# Node.js
RUN yarn install

# Python
RUN pip install -r requirements.txt

# Java
RUN mvn dependency:resolve
```

---

## Customizing the Build Flow

The build flow is defined in `Dockerfile.hud`. Key sections:

### Project setup

Controls how the target repository is loaded. By default, it clones from `REPO_URL` at build time.

```dockerfile
ARG REPO_URL="https://github.com/hud-evals/coding-template-sample"      # Clone from URL
ARG FOLDER_NAME="project"                                                # Destination folder
```

### Git protection

Protects `.git` from agent access so they can't peek at solutions:

```dockerfile
USER root
RUN chown -R root:root /home/ubuntu/${FOLDER_NAME}/.git && \
    chmod -R 700 /home/ubuntu/${FOLDER_NAME}/.git
USER ubuntu
```

### MCP server setup

Installs the evaluation environment and tools:

```dockerfile
COPY ./env.py /mcp_server/env.py
COPY ./grading /mcp_server/grading
COPY ./tasks.py /mcp_server/tasks.py
```

---

## Customizing the Testing Flow

### How the grading runner works

The default grading logic lives in `grading/runner.py`. The `GradingRunner.grade()` method does the following:

1. **Copies the repo** to an isolated `/tmp/grading_<uuid>` directory so grading doesn't affect the agent's working copy.
2. **Applies `test.patch`** via `git apply`. This patch (generated at runtime from `base` → `test` branch) adds hidden test files into the copy.
3. **Calls `run_tests()`**, which formats and runs the `test_command` string (default: `uv run pytest {test_files}`) via `bash -lc` in the copied directory.
4. **Returns 1.0** if the tests pass (exit code 0), **0.0** otherwise.

The default `test_command` is `uv run pytest {test_files}`, where `{test_files}` is replaced with the space-joined list of test file names you pass to `AgentPatchGrader.grade()`.

### Simple: Configure the test command

For many projects you only need to change the test command string:

```python
AgentPatchGrader.grade(
    weight=1.0,
    problem_id="my_task",
    test_files=["test_foo.py"],
    test_command="pytest {test_files}",  # Or: yarn test, go test, make test
)
```

### Advanced: Custom test logic

If you are switching to a different software project (e.g., TypeScript, Java, Rust), the default `run_tests()` method in `grading/runner.py` will likely need to change. The default implementation runs a single shell command and checks its exit code, but your project may require a build step, a running server, or other setup before tests can execute.

To customize this, subclass `GradingRunner` and override `run_tests()`. The method receives no arguments -- use `self.working_dir` (the isolated copy of the repo) and `self.test_files`. Return a tuple of `(success: bool, metadata: dict)`.

The following is a sketch for a hypothetical TypeScript project that uses yarn:

```python
import subprocess
import time
from grading import GradingRunner

class YarnTestRunner(GradingRunner):
    def run_tests(self) -> tuple[bool, dict]:
        # Build the project first
        subprocess.run(["yarn", "build"], cwd=self.working_dir, check=True)
        
        # Start the dev server (some tests may need it running)
        server = subprocess.Popen(["yarn", "start"], cwd=self.working_dir)
        time.sleep(5)
        
        # Run the test suite
        result = subprocess.run(
            ["yarn", "test", *self.test_files],
            cwd=self.working_dir,
            capture_output=True,
            text=True,
        )
        
        # Clean up
        server.terminate()
        
        return result.returncode == 0, {
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
```

To use your custom runner, update `grading/graders.py` to instantiate it instead of the default `GradingRunner` in `AgentPatchGrader.compute_score()`.

---

## Updating Package Name

Edit `pyproject.toml`:

```toml
[project]
name = "your-company-evaluation-framework"
description = "AI Agent Evaluation Framework for [Your Project]"
```

---

## Database Configuration

If your tests need a database, set it up in the test command or Dockerfile.

**MySQL:**
```python
drop_cmd = f"mysql -u root -p{password} -e 'DROP DATABASE IF EXISTS {db_name}'"
create_cmd = f"mysql -u root -p{password} -e 'CREATE DATABASE {db_name}'"
```

**MongoDB:**
```python
drop_cmd = f"mongo {db_name} --eval 'db.dropDatabase()'"
```

---

## User Context

If your project doesn't run as `ubuntu`:

```python
# In tools/bash.py - remove sudo wrapper
subprocess.run(["bash", "-lc", command], ...)

# Or use a different user
subprocess.run(["sudo", "-u", "youruser", "bash", "-lc", command], ...)
```

---

## Quick Reference

| File | Purpose |
|------|---------|
| `tasks.py` | Task definitions (`.task()` calls on the `coding-bug` scenario) |
| `grading/graders.py` | Grading logic |
| `grading/runner.py` | Test execution |
| `Dockerfile.hud` | Build configuration |
| `env.py` | MCP server and tools |
