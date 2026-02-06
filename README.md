# Coding Environment Template

A coding environment for agent evaluations. Provides bash and file editing tools.

> **⚠️ This is a template.** Before building, customize `Dockerfile.hud` for your project.

## Quick Start

```bash
uv sync
uv run imagectl4.py my-image -bvr  # Build, validate, and run
```

## Getting Started

### Local

These instructions are for running tasks locally. Telemetry from your runs will be uploaded to HUD's platform.

**1. Clone and Initialize**

```bash
git clone https://github.com/hud-evals/coding-template
cd coding-template
uv sync
```

**2. Build, Validate, and Run**

```bash
# Build the Docker image
uv run imagectl4.py my-image -b

# Validate that your task branches and grading are correct
uv run imagectl4.py my-image -v

# Run an agent against scenarios
uv run imagectl4.py my-image -r

# Or combine all three
uv run imagectl4.py my-image -bvr
```

Use `--ids` to target specific scenarios:
```bash
uv run imagectl4.py my-image -bvr --ids my-task-1 my-task-2
```

### Remote

These instructions are for running remote jobs. You only have access to these if you are a HUD enterprise customer: contact founders@hud.ai to learn more.

**1. Deploy to Platform**

Connect this repo to hud.ai:

1. Push to GitHub (or clone this template repository)
2. Go to [hud.ai](https://hud.ai) → **Environments** → **New Environment**
3. Connect your GitHub repo
4. (Optional) Set `CODING_GITHUB_TOKEN` build arg if using a private repo
5. Your environment builds automatically on each push

Once deployed, your environment is accessible by its slug (e.g., `my-org/coding`).

Deploy requires `REPO_URL`:
```bash
hud deploy . --build-arg REPO_URL=https://github.com/your-org/your-repo
```

For private repos, add: `--secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN`

**2. Create a Taskset and Add Your First Task**

1. Go to **Tasksets** → **New Taskset** and create a new taskset
2. Go to your environment and enter `sample-json-bug` as the scenario. This corresponds to the task in `tasks/basic.py`.
3. Click on "Create Task" and add this to your taskset.

**3. Run Your First Task**

1. Go to your taskset. Under "Tasks", you should be able to see your `sample-json-bug` task.
2. Click on "Run Taskset". Click on "Claude Sonnet 4.5" and set the "Max Steps" to 20 and "Group Size" to 5.
3. Click on "Run [N] Tasks", which should open the page for the job you've just launched.

### Build Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `REPO_URL` | `https://github.com/hud-evals/coding-template-sample` | Repository to clone (override for your repo) |
| `FOLDER_NAME` | `project` | Destination folder in container |

## Key Concepts

### 3-Branch Pattern

Every task in `tasks/*.py` follows the **3-branch pattern**, where each branch exists in the target repo:
| Branch | Purpose |
|--------|---------|
| `baseline` | Starting state the agent sees, where the agent makes changes |
| `test` | Contains tests that grade the agent's solution |
| `golden` | Correct solution for validation and/or training |

Git patches will automatically be generated for every branch defined in each task.

If you're **not using git-based problems**, comment out the git setup section in `Dockerfile.hud`.

### Tools (in `env.py`)

```python
@env.tool()
async def bash(command: str) -> str:
    """Run a bash command."""

@env.tool()
async def editor(command: str, path: str, ...) -> str:
    """View, create, and edit files."""
```

### Tasks (in `tasks/*.py`)

```python
from env import env, setup_task, make_prompt
from grading import AgentPatchGrader, Grade, ValidateMode

@env.scenario("sample-json-bug")
async def sample_json_bug(hints_enabled: bool = False, validate_mode: ValidateMode | None = None):
    """Fix the JSON serialization bug in server.py."""
    
    setup_task(
        task_id="sample_json_bug",
        base="server_fix_baseline",
        test="server_fix_test",
        golden="server_fix_golden",
        validate_mode=validate_mode,
    )
    
    prompt = make_prompt("""Fix the JSON serialization bug in server.py.

The API server's responses are malformed. When you make a request to any endpoint,
the response body is not valid JSON - it looks like a Python dict representation
instead of proper JSON (e.g., single quotes instead of double quotes).
""")
    
    _ = yield prompt
    
    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="sample_json_bug",
            test_files=["test_server.py"],
            validate_mode=validate_mode,
        )
    ])
    yield grade.score
```

The `validate_mode` parameter is used by `imagectl4.py -v` to test that your branches and grading are correctly configured. It is passed automatically during validation -- you just need to thread it through to `setup_task()` and `AgentPatchGrader.grade()` as shown above.

## Generate Task JSON

Use `imagectl4.py -j` to generate `problem-metadata.json` and `remote_tasks.json`. The latter is used by `hud eval` for remote evaluation:

```bash
uv run imagectl4.py my-image -j # all scenarios
uv run imagectl4.py my-image -j --ids my-task  # specific scenarios only
```

## Run Evaluations

### Remote (Platform GUI)

Run evaluations at scale directly on [hud.ai](https://hud.ai) with parallel execution and automatic tracing. See the [Remote getting started](#remote) section above for setup.

### Remote (CLI)

Use `hud eval` with `remote_tasks.json` (generated by `imagectl4.py -j`) to run evaluations on the HUD platform:

```bash
hud eval ./remote_tasks.json --model gpt-4o --remote  # https://hud.ai/models
hud eval my-org/coding-tasks --model gpt-4o --remote --group 5
```

### Local (CLI)

Use `imagectl4.py` to build, validate, and run scenarios locally. This is the recommended workflow for development and quick iteration:

```bash
# Build + validate + run all scenarios
uv run imagectl4.py my-image -bvr

# Target specific scenarios
uv run imagectl4.py my-image -bvr --ids my-task-1 my-task-2

# Run with a custom step limit
uv run imagectl4.py my-image -r --ids my-task --max-steps 30
```

> **Note:** Local runs execute one task at a time in a single container. For parallel execution, use remote evaluation.

## Local Development

This environment requires Docker. Use `imagectl4.py` for local development and quick iteration:

```bash
uv sync

# Build the Docker image
uv run imagectl4.py my-image -b

# Validate your tasks
uv run imagectl4.py my-image -v

# Run an agent against your scenarios
uv run imagectl4.py my-image -r

# Or combine all three
uv run imagectl4.py my-image -bvr
```

Edit tasks in `tasks/*.py` or grading in `grading/`, then rebuild and re-validate with `-bv`.

**When to rebuild:** Any change to task definitions, grading logic, Dockerfile, system packages, or service configs.

## Structure

```
coding-template/
├── env.py              # Tools + scenario registration
├── tools/              # bash, editor
├── grading/            # Grading logic and test runners
├── tasks/              # Problem definitions
├── local_test.py       # Dev testing
└── Dockerfile.hud      # Container config
```

## Further Reading

- **[Customization Guide](CUSTOMIZATION_GUIDE.md)** — Creating tasks, configuring builds, writing custom graders
- **[CLI Reference](HUD_CLI_GUIDE.md)** — `imagectl4.py` flags and `hud` commands
- **[Full Documentation](https://docs.hud.ai)** — Platform documentation
