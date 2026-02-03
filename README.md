# Coding Environment Template

A coding environment for agent evaluations. Provides bash and file editing tools.

> **⚠️ This is a template.** Before building, customize `Dockerfile.hud` for your project.

## Quick Start (Sample Repo)

To test the template with the sample repository:

```bash
hud build . --build-arg REPO_URL=https://github.com/hud-evals/coding-template-sample
hud dev --port 8765
python local_test.py
```

## Template Setup

The Dockerfile uses two build arguments:

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `REPO_URL` | **Yes** | *(none)* | Git repository URL to clone |
| `FOLDER_NAME` | No | `project` | Folder name for the cloned repo |

```dockerfile
# Required: Pass REPO_URL as a build argument
ARG REPO_URL
ARG FOLDER_NAME="project"

# The repo is cloned to /home/ubuntu/${FOLDER_NAME}
WORKDIR /home/ubuntu/${FOLDER_NAME}
```

For private repos, set `CODING_GITHUB_TOKEN` locally before building:

```bash
export CODING_GITHUB_TOKEN=github_pat_XXX
hud build . --build-arg REPO_URL=https://github.com/your-org/your-repo \
            --secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN
```

Every task in `tasks/*.py` follows the **3-branch pattern**, where each branch exists in the source repo cloned in the Dockerfile:
| Branch | Purpose |
|--------|---------|
| `baseline` | Starting state the agent sees, where the agent makes changes |
| `test` | Contains tests that grade the agent's solution |
| `golden` | Correct solution for validation and/or training |

Git patches will automatically be generated for every branch defined in each task.

If you're **not using git-based problems**, comment out the git clone section in `Dockerfile.hud` (lines ~63-87).

## 1. Deploy to Platform

If you haven't already, connect this repo to hud.ai:

1. Push to GitHub
2. Go to [hud.ai](https://hud.ai) → **New** → **Environment**
3. Connect your GitHub repo
4. Your environment builds automatically on each push

Once deployed, your environment is accessible by its slug (e.g., `my-org/coding`).

## 2. Define Tools and Scenarios

Tools are functions agents can call. Scenarios define the evaluation lifecycle.

### Tools (in `env.py`)

```python
@env.tool()
async def bash(command: str) -> str:
    """Run a bash command."""

@env.tool()
async def editor(command: str, path: str, ...) -> str:
    """View, create, and edit files."""
```

### Scenarios (in `scenarios.py`)

```python
@env.scenario("solve-task")
async def solve_task(problem_id: str, hints_enabled: bool = False):
    await env.call_tool("_start_services")                    # Setup
    prompt = spec_to_statement(get_problem_spec(problem_id))
    _ = yield prompt                                          # Prompt → agent runs
    result = await env.call_tool("_grade_solution", {"problem_id": problem_id})
    yield result["score"]                                     # Reward
```

### Tasks (in `tasks/*.py`)

```python
from grading import problem, Grade, AgentPatchGrader

@problem(
    id="fix-bug",
    description="Fix the login bug in auth.py",
    difficulty="easy",
    base="main", test="test-branch", golden="golden-branch",
)
def fix_bug() -> Grade:
    return Grade.from_subscores([
        AgentPatchGrader.grade(weight=1.0, ...)
    ])
```

## 3. Create Tasks from Scenarios

Tasks are scenario instances with specific arguments.

**In Code:**

```python
task = env("solve-task", problem_id="fix-bug")
```

**From JSON (`remote_tasks.json`):**

```json
{
  "env": {"name": "my-org/coding"},
  "scenario": "solve-task",
  "args": {"problem_id": "fix-bug", "hints_enabled": false}
}
```

**On Platform:**

After deploying, create tasks from your scenarios on hud.ai. Access them by slug:

```python
from hud.datasets import load_tasks
tasks = load_tasks("my-org/coding-tasks")
```

## 4. Run Evaluations

Run tasks and see results on hud.ai. You have three options:

**On Platform:**

Run evaluations at scale directly on [hud.ai](https://hud.ai) with parallel execution and automatic tracing.

**CLI:**

```bash
hud eval ./remote_tasks.json --model gpt-4o --remote  # https://hud.ai/models
hud eval my-org/coding-tasks --model gpt-4o --remote --group 5
```

**Python:**

```python
import hud
from hud.agents import OpenAIChatAgent  # See all models: https://hud.ai/models

task = env("solve-task", problem_id="fix-bug")

async with hud.eval(task) as ctx:
    agent = OpenAIChatAgent.create(model="gpt-4o")  # Uses inference.hud.ai
    await agent.run(ctx)

# Results are automatically traced to hud.ai
```

**With Variants (A/B Testing):**

```python
tasks = [env("solve-task", problem_id="fix-bug"), env("solve-task", problem_id="add-feature")]
variants = {"model": ["gpt-4o-mini", "gpt-4o"]}

async with hud.eval(tasks, variants=variants, group=2) as ctx:
    agent = OpenAIChatAgent.create(model=ctx.variants["model"])
    await agent.run(ctx)
```

## Local Development

This environment requires Docker. Use `hud dev` with hot-reload:

```bash
# 1. Build the Docker image (first time only)
hud build . --build-arg REPO_URL=https://github.com/your-org/your-repo

# For private repos, also pass the secret:
hud build . --build-arg REPO_URL=https://github.com/your-org/your-repo \
            --secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN

# 2. Start with hot-reload on tasks/grading
hud dev -w tasks -w grading --port 8765

# 3. Test locally
python local_test.py
```

> ⚠️ **Local runs one task at a time.** The local environment uses a single container, so tasks run sequentially. For parallel execution, push and run remotely:
> ```bash
> hud push
> hud eval ./remote_tasks.json --model gpt-4o --remote --group 5
> ```

### Hot-Reload

When you save a watched file, the MCP server restarts with fresh imports:

| Component | Reloaded? |
|-----------|-----------|
| `tasks/*.py` | ✅ Yes |
| `grading/*.py` | ✅ Yes |
| `tools/*.py` | ✅ Yes (if watched) |

**When to rebuild:** Dockerfile changes, system packages, service configs.

## Structure

```
coding-template/
├── env.py              # Tools + scenario registration
├── scenarios.py        # Shared helpers + scenarios
├── tools/              # bash, editor
├── grading/            # @problem decorator, graders
├── tasks/              # Problem definitions
├── local_test.py       # Dev testing
└── Dockerfile.hud      # Container config
```

## Customization Guide

This template is designed to be adapted for different tech stacks. Here's how to customize it for your project.

### 1. Update Package Name

Edit `pyproject.toml`:

```toml
[project]
name = "your-company-evaluation-framework"
description = "AI Agent Evaluation Framework for [Your Project]"
```

### 2. Configure Your Tech Stack

In `Dockerfile.hud`, uncomment and configure the section for your language:

**Python:**
```dockerfile
RUN python3 -m pip install --upgrade pip
RUN pip install poetry  # or: pipenv, pip-tools
RUN cd /home/ubuntu/${FOLDER_NAME} && pip install -r requirements.txt
```

**Java/Maven:**
```dockerfile
RUN apt-get install -y openjdk-17-jdk maven
RUN cd /home/ubuntu/${FOLDER_NAME} && mvn dependency:resolve
```

**Go:**
```dockerfile
RUN wget https://go.dev/dl/go1.21.0.linux-amd64.tar.gz && tar -C /usr/local -xzf go*.tar.gz
RUN cd /home/ubuntu/${FOLDER_NAME} && go mod download
```

**Rust:**
```dockerfile
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
RUN cd /home/ubuntu/${FOLDER_NAME} && cargo fetch
```

### 3. Configure Test Framework

The grading system requires JUnit XML output. Configure your test framework:

**pytest:**
```python
# In grading/runner.py
def run_pytest_tests(self) -> str:
    result = subprocess.run(
        ["pytest", "--junit-xml=pytest_results.xml"] + self.test_files,
        cwd=self.grade_working_dir, capture_output=True, text=True,
    )
    return Path(self.grade_working_dir, "pytest_results.xml").read_text()
```

**Go test:**
```python
def run_go_tests(self) -> str:
    result = subprocess.run(
        ["go", "test", "-v", "./...", "-json"],
        cwd=self.grade_working_dir, capture_output=True, text=True,
    )
    return self._convert_go_json_to_junit(result.stdout)
```

### 4. Database Configuration

Adapt or remove database setup in `grading/runner.py`:

**No database:**
```python
# Comment out database reset steps in run_grading()
```

**MySQL:**
```python
drop_cmd = f"mysql -u root -p{password} -e 'DROP DATABASE IF EXISTS {db_name}'"
create_cmd = f"mysql -u root -p{password} -e 'CREATE DATABASE {db_name}'"
```

**MongoDB:**
```python
drop_cmd = f"mongo {db_name} --eval 'db.dropDatabase()'"
```

### 5. User Context

If your project doesn't run as `ubuntu`:

```python
# In tools/bash.py - remove sudo wrapper
subprocess.run(["bash", "-lc", command], ...)

# Or use a different user
subprocess.run(["sudo", "-u", "youruser", "bash", "-lc", command], ...)
```

## Documentation

Full documentation: [docs.hud.ai](https://docs.hud.ai)
