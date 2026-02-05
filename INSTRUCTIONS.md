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
from grading import AgentPatchGrader, Grade

@env.scenario("my-task")
async def my_task(hints_enabled: bool = False):
    """Short description of the task."""
    
    # Set up git branches and patches
    setup_task(
        task_id="my_task",
        base="my_task_baseline",
        test="my_task_test",
        golden="my_task_golden",
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
            base="my_task_baseline",
            test="my_task_test",
            golden="my_task_golden",
            test_files=["test_foo.py"],
        )
    ])
    
    yield grade.score
```

### 3. Validate your task

Before testing with an agent, verify your branches are set up correctly:

```bash
hud dev -w tasks -w grading --port 8765

# In another terminal, edit local_test.py and uncomment:
# await validate_golden()

python local_test.py
```

This checks that:
- The golden branch can be checked out
- Tests pass on the golden branch

### 4. Test with an agent

```bash
# Uncomment in local_test.py:
# await test_scenario()

python local_test.py
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

### Project setup (lines 43-88)

Controls how the target repository is loaded:
- **Local builds**: Copies from submodule
- **Deploy builds**: Clones from `REPO_URL`

```dockerfile
ARG PROJECT_SUBMODULE="coding-template-sample"  # Change default submodule
ARG REPO_URL=""                                  # Or clone from URL
ARG FOLDER_NAME="project"                        # Destination folder
```

### Git protection (lines 91-101)

Protects `.git` from agent access so they can't peek at solutions:

```dockerfile
USER root
RUN chown -R root:root /home/ubuntu/${FOLDER_NAME}/.git && \
    chmod -R 700 /home/ubuntu/${FOLDER_NAME}/.git
USER ubuntu
```

### MCP server setup (lines 180+)

Installs the evaluation environment and tools:

```dockerfile
COPY ./env.py /mcp_server/env.py
COPY ./grading /mcp_server/grading
COPY ./tasks /mcp_server/tasks
```

---

## Customizing the Testing Flow

### Using different test runners

Edit `grading/runner.py` to add support for your test framework:

```python
# In GradingRunner.run_tests()
def run_tests(self, test_files: list[str]) -> tuple[bool, dict]:
    # Run your test command
    result = subprocess.run(
        ["pytest", "--junitxml=results.xml"] + test_files,
        capture_output=True
    )
    
    # Parse JUnit XML results
    return self.parse_junit_results("results.xml")
```

### Custom graders

Create new graders in `grading/graders.py`:

```python
class MyCustomGrader(Grader):
    name = "MyCustomGrader"
    
    @classmethod
    def compute_score(cls, **kwargs) -> tuple[float, dict]:
        # Your grading logic
        # Return (score, metadata)
        return (1.0, {"passed": True})
```

Use in tasks:

```python
grade = Grade.from_subscores([
    MyCustomGrader.grade(weight=0.5, some_param="value"),
    AgentPatchGrader.grade(weight=0.5, ...),
])
```

### JUnit XML requirement

The grading system expects JUnit XML format. Configure your test framework:

**pytest:**
```bash
pytest --junitxml=results.xml
```

**Jest:**
```bash
jest --reporters=jest-junit
```

**Go:**
```bash
go test -v 2>&1 | go-junit-report > results.xml
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
| `local_test.py` | Local testing script |
