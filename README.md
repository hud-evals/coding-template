# Coding Environment Template

A coding environment for agent evaluations. Provides bash and file editing tools.

> **⚠️ This is a template.** Before building, customize `Dockerfile.hud` for your project.

## Quick Start (Sample Repo)

To test the template with the included sample submodule:

```bash
git submodule update --init  # Ensure submodule is populated
hud build .
hud dev --port 8765
python local_test.py
```

## Template Setup

### Local Development (`hud build`)

**Submodule mode (offline, default):**
```bash
git submodule update --init
hud build .
```

**URL mode:**
```bash
hud build . --build-arg REPO_URL=https://github.com/your-org/your-repo
```

### Deploy (`hud deploy`)

Deploy **requires** `REPO_URL` (submodule mode only works locally):
```bash
hud deploy . --build-arg REPO_URL=https://github.com/your-org/your-repo
```

For private repos, add: `--secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN`

### Build Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `PROJECT_SUBMODULE` | `coding-template-sample` | Submodule to use (local only) |
| `REPO_URL` | *(empty)* | Clone from URL (required for deploy) |
| `FOLDER_NAME` | `project` | Destination folder in container |

### 3-Branch Pattern

Every task in `tasks/*.py` follows the **3-branch pattern**, where each branch exists in the target repo:
| Branch | Purpose |
|--------|---------|
| `baseline` | Starting state the agent sees, where the agent makes changes |
| `test` | Contains tests that grade the agent's solution |
| `golden` | Correct solution for validation and/or training |

Git patches will automatically be generated for every branch defined in each task.

If you're **not using git-based problems**, comment out the git setup section in `Dockerfile.hud`.

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
from env import env, setup_task, make_prompt
from grading import AgentPatchGrader, Grade

@env.scenario("fix-bug")
async def fix_bug(hints_enabled: bool = False):
    """Fix the login bug in auth.py."""
    
    setup_task(
        task_id="fix_bug",
        base="fix_bug_baseline",
        test="fix_bug_test",
        golden="fix_bug_golden",
    )
    
    prompt = make_prompt("Fix the login bug in auth.py...")
    _ = yield prompt
    
    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            base="fix_bug_baseline",
            test="fix_bug_test",
            golden="fix_bug_golden",
            test_files=["test_auth.py"],
        )
    ])
    yield grade.score
```

## 3. Create Tasks from Scenarios

Tasks are scenario instances.

**In Code:**

```python
task = env("fix-bug")
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
git submodule update --init
hud build .

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

### 3. Configure Test Command

The grading system runs your test command and checks the exit code (0 = pass).

Set your test command in `tasks/*.py`:

```python
AgentPatchGrader.grade(
    weight=1.0,
    problem_id="my_task",
    test_files=["test_foo.py"],
    test_command="pytest {test_files}",  # Or: yarn test, go test, etc.
)
```

### 4. Database Configuration (optional)

If your tests need a database, set it up in the test command or Dockerfile.

**Example:**
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
