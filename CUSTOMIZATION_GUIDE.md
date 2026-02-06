# Customization Guide

## Creating New Tasks

Tasks are defined in `tasks/*.py` using the `@env.scenario` decorator.

### 1. Set up branches in your target repo

Each task needs 3 branches:
- `baseline` - Starting state (bug present, no tests)
- `test` - Adds test files that verify the fix
- `golden` - Contains the correct solution

### 2. Define the scenario

```python
# tasks/basic.py
from env import env, setup_task, make_prompt
from grading import AgentPatchGrader, Grade, ValidateMode

@env.scenario("my-task")
async def my_task(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Short description of the task."""
    
    # Set up git branches and patches
    setup_task(
        task_id="my_task",
        base="my_task_baseline",
        test="my_task_test",
        golden="my_task_golden",
        validate_mode=validate_mode,
    )
    
    # Define the prompt shown to the agent
    prompt = make_prompt("""Fix the bug in foo.py.
    
The function returns incorrect results when given negative numbers.
""")
    
    # Yield prompt, wait for agent to finish
    _ = yield prompt
    
    # Grade the solution
    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="my_task",
            test_files=["test_foo.py"],
            validate_mode=validate_mode,
        )
    ])
    
    yield grade.score
```

### 3. Build the Docker image

Build the image before validating or running:

```bash
uv run imagectl4.py my-image -b
```

### 4. Validate your task

Before testing with an agent, validate that your branches and grading are set up correctly:

```bash
# Validate all registered scenarios
uv run imagectl4.py my-image -v

# Validate specific scenarios only
uv run imagectl4.py my-image -v --ids my-task
```

If `--ids` is omitted, `imagectl4.py` auto-discovers every scenario registered via `@env.scenario()` in `tasks/`.

**How validation works:** Validation runs each scenario with zero agent steps (the agent does nothing) and then evaluates the grader. Each scenario is tested in two modes:

- **`baseline_fail`** — The environment starts on the baseline branch (the buggy code). Since the agent takes no steps, the tests should *fail*. The grader detects this failure and inverts the score, so a correctly-configured task reports `reward = 1.0`.
- **`golden_pass`** — The environment starts on the golden branch (the correct solution). Since the solution is already in place, the tests should *pass*, and the grader reports `reward = 1.0` directly.

Both modes must return `reward = 1.0` for validation to pass. If either mode fails, it means your branches, patches, or grading logic are misconfigured. Common issues:

- `baseline_fail` returns 0 — The baseline branch already passes the tests (the bug isn't actually present, or test branch is wrong).
- `golden_pass` returns 0 — The golden branch doesn't pass the tests (the solution is incomplete, or the test files don't match).

### 5. Test with an agent

Once validation passes, run an agent against your scenarios:

```bash
# Run all scenarios
uv run imagectl4.py my-image -r

# Run specific scenarios with custom step limit
uv run imagectl4.py my-image -r --ids my-task --max-steps 30
```

### 6. Build, validate, and run in one command

Flags can be combined. Actions always execute in order: build, validate, run, push, json.

```bash
# Build + validate + run
uv run imagectl4.py my-image -bvr

# Full pipeline: build, validate, run, push, and generate metadata
uv run imagectl4.py my-image -bvrpj --ids my-task
```

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
COPY ./tasks /mcp_server/tasks
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
| `tasks/*.py` | Task definitions |
| `grading/graders.py` | Grading logic |
| `grading/runner.py` | Test execution |
| `Dockerfile.hud` | Build configuration |
| `env.py` | MCP server and tools |
| `imagectl4.py` | Build, validate, run, push, and JSON generation |
