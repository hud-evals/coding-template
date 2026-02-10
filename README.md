# Git-Enabled Coding Environment Template

A coding environment for agent evaluations where agents have **full git access**. Forked from [`hud-evals/coding-template`](https://github.com/hud-evals/coding-template).

Unlike the original template (which locks `.git`), this template gives agents access to `git log`, `git blame`, `git diff`, `git commit`, and all other git commands — enabling realistic SDLC-style evaluations.

> **How it works:** At Docker build time, test/golden patches are extracted and grading branches are deleted from the repo. The agent gets a real git repo with full history but no way to see the solution.

## Quick Start

```bash
uv sync
uv run imagectl4.py -bvr  # Build, validate, and run
```

## Getting Started

### Local

**1. Clone and Initialize**

```bash
git clone https://github.com/hud-evals/coding-template-with-git
cd coding-template-with-git
uv sync
```

**2. Configure Your Task**

Edit `task_config.yaml` to define your task's git configuration:

```yaml
tasks:
  my-task:
    worktree:
      checkout: baseline              # Branch the agent starts on
      include_branches:               # What branches the agent sees
        - baseline
        - main
      # snapshot_before: "2026-01-15" # Optional: truncate history
    grading:
      test_branch: test               # Hidden: contains test files
      golden_branch: golden           # Hidden: contains solution
      test_files: ["tests/test_fix.py"]
    prompt: |                          # Task prompt (used by both HUD and Taiga)
      Fix the bug in foo.py...
```

**3. Define Your Scenario**

In `tasks/basic.py`:

```python
@env.scenario("my-task")
async def my_task(hints_enabled=False, validate_mode=None):
    setup_task(
        task_id="my-task",        # Must match key in task_config.yaml
        checkout="baseline",       # Branch from worktree.checkout
        validate_mode=validate_mode,
    )
    prompt = make_prompt("Fix the bug in foo.py...")
    _ = yield prompt
    grade = Grade.from_subscores([
        AgentPatchGrader.grade(
            weight=1.0,
            problem_id="my-task",
            test_files=["tests/test_fix.py"],
            validate_mode=validate_mode,
        )
    ])
    yield grade.score
```

**4. Build, Validate, and Run**

```bash
uv run imagectl4.py -b                         # Build Docker image
uv run imagectl4.py -v --ids my-task            # Validate (baseline_fail + golden_pass)
uv run imagectl4.py -r --ids my-task            # Run agent
uv run imagectl4.py -bvr --ids my-task          # All three
```

### Remote (HUD Platform)

**1. Deploy to Platform**

```bash
hud deploy . --build-arg REPO_URL=https://github.com/your-org/your-repo
```

For private repos, add: `--secret id=CODING_GITHUB_TOKEN,env=CODING_GITHUB_TOKEN`

**2. Create a Taskset and Run**

1. Go to [hud.ai](https://hud.ai) → **Environments** → Connect your GitHub repo
2. Create a taskset with your scenario name
3. Run with your preferred model and step limit

### Remote (Taiga Platform)

This template also supports the Taiga evaluation platform. Build with `IS_TAIGA=1`:

```bash
# Build for Taiga
docker build -f Dockerfile.hud --build-arg IS_TAIGA=1 \
  -t your-registry/your-image:tag .

# Push to your registry
docker push your-registry/your-image:tag
```

When `IS_TAIGA=1`, the environment registers `setup_problem` and `grade_problem` tools instead of using HUD scenarios. Taiga provides `bash` and `str_replace_editor` tools natively.

Update `taiga_problem.json` with your image URL and task IDs, then submit to the Taiga platform.

### Build Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `REPO_URL` | `https://github.com/hud-evals/coding-template-sample` | Repository to clone |
| `FOLDER_NAME` | `project` | Destination folder in container |
| `IS_TAIGA` | `0` | Set to `1` for Taiga platform support |

## Key Concepts

### Git-Enabled vs Original Template

| Feature | Original Template | This Template |
|---------|------------------|---------------|
| Agent git access | Blocked (`.git` root-only) | **Full access** |
| `git log`, `git blame` | Not available | Available |
| `git commit` | Not available | Available |
| Patch extraction | Runtime | **Build time** |
| Solution hidden via | `.git` permissions | **Branch deletion + gc** |

### 3-Branch Pattern

Same as the original template, each task needs 3 branches in the target repo:

| Branch | Purpose |
|--------|---------|
| `baseline` | Starting state the agent sees |
| `test` | Contains tests that grade the agent's solution |
| `golden` | Correct solution for validation |

The key difference: `test` and `golden` branches are **deleted** from the repo at build time (after patches are extracted). The agent only sees the branches listed in `task_config.yaml`.

### task_config.yaml

Controls what the agent sees and how grading works:

```yaml
tasks:
  my-task:
    worktree:
      checkout: baseline           # Starting branch
      include_branches:            # Visible branches (optional)
        - baseline
      snapshot_before: "2026-01-15" # Truncate history (optional)
    grading:
      test_branch: test            # Hidden test branch
      golden_branch: golden        # Hidden solution branch
      test_files: ["test_foo.py"]  # Test files in test branch
      test_command: "..."          # Custom test command (optional)
    prompt: |                       # Task prompt
      Fix the bug...
```

### Build-Time Git Setup

`build_scripts/setup_git.py` runs during Docker build:

1. Reads `task_config.yaml`
2. Extracts `test.patch` and `golden.patch` into `/home/root/patches/` (root-only)
3. Deletes grading branches from the repo
4. Removes the `origin` remote (cleans up all refs)
5. Runs `git gc --prune=now --aggressive` to purge deleted objects
6. Leaves `.git` accessible to the agent

### Dual-Mode Operation

The environment supports two platforms:

**HUD Mode** (default): Uses `@env.scenario()` decorators in `tasks/`. Setup and grading happen via the yield-based scenario pattern.

**Taiga Mode** (`IS_TAIGA=1`): Registers `setup_problem` and `grade_problem` as MCP tools. Taiga calls them directly. Task config is read from `task_config.yaml` at runtime.

Both modes share the same underlying `setup_task()` and `AgentPatchGrader` logic.

### Tools

```python
@env.tool()
async def bash(command: str) -> str:
    """Run a bash command (including git commands)."""

@env.tool()
async def editor(command: str, path: str, ...) -> str:
    """View, create, and edit files."""
```

In Taiga mode, `bash` and `editor` are provided natively by the platform (`required_tools: ["str_replace_editor", "bash"]`).

## Validation

Validation ensures your branches and grading are correctly configured:

```bash
uv run imagectl4.py -v --ids my-task
```

Two modes are tested (both must return `reward = 1.0`):

- **`baseline_fail`**: Baseline branch has the bug → tests fail → inverted score = 1.0
- **`golden_pass`**: Baseline + golden.patch applied → tests pass → score = 1.0

## Testing

```bash
# Unit tests for build-time git setup (no Docker needed)
uv run --extra dev pytest tests/test_setup_git.py -v

# Full Docker validation
uv run imagectl4.py -bv --ids sample-json-bug
```

## Generate Task JSON

```bash
uv run imagectl4.py -j                    # All scenarios
uv run imagectl4.py -j --ids my-task      # Specific scenarios
```

## Structure

```
coding-template-with-git/
├── env.py              # Tools + scenario registration + Taiga tools
├── task_config.yaml    # Per-task git/branch/prompt configuration
├── taiga_problem.json  # Taiga problem definition template
├── tools/              # bash, editor
├── grading/            # Grading logic and test runners
├── tasks/              # Problem definitions (HUD scenarios)
├── tests/              # Unit tests for setup_git.py
├── build_scripts/
│   ├── setup_git.py    # Build-time git setup (patch extraction, branch pruning)
│   └── alter_env_files.py  # Environment file configuration
├── Dockerfile.hud      # Container config (supports IS_TAIGA build arg)
├── imagectl4.py        # Build, validate, run CLI
└── IMPLEMENTATION_PLAN.md  # Detailed design document
```

## Further Reading

- **[Customization Guide](CUSTOMIZATION_GUIDE.md)** — Creating tasks, configuring builds, writing custom graders
- **[Implementation Plan](IMPLEMENTATION_PLAN.md)** — Detailed design and architecture
- **[CLI Reference](HUD_CLI_GUIDE.md)** — `imagectl4.py` flags and `hud` commands
- **[Full Documentation](https://docs.hud.ai)** — Platform documentation
